const $ = (id) => document.getElementById(id);
const SENT = ["Positive", "Neutral", "Negative"];
const PAGE = 25;

let data = null, jobId = null, scope = "all", page = 0, charts = {};

const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const sentColor = () => ({ Positive: css("--pos"), Neutral: css("--neu"), Negative: css("--neg") });

// ---- run analysis ----
$("form").onsubmit = async (e) => {
  e.preventDefault();
  show("error", false); show("warn", false); show("welcome", false);
  $("go").disabled = true;
  show("progress", true);
  setProgress("Starting…", 3);
  try {
    const res = await fetch("/api/analyze", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: $("mode").value, order: $("order").value, pack: $("pack").value,
        query: $("query").value.trim(), region: $("region").value.trim() || "PK",
        max_videos: +$("videos").value, max_comments: +$("comments").value,
      }),
    });
    if (!res.ok) throw new Error((await res.json()).detail?.[0]?.msg || "Request failed");
    jobId = (await res.json()).job_id;
    await poll();
  } catch (err) {
    showError(err.message);
  } finally {
    $("go").disabled = false;
  }
};

async function poll() {
  for (;;) {
    const j = await (await fetch(`/api/jobs/${jobId}`)).json();
    if (j.status === "error") throw new Error(j.error);
    if (j.status === "done") {
      show("progress", false);
      data = j.result; page = 0;
      return render();
    }
    let pct = 5;
    if (j.videos_total) pct = 5 + (j.videos_done / j.videos_total) * 40;
    if (j.comments_total) pct = 45 + (j.comments_scored / j.comments_total) * 55;
    const extra = j.comments_total ? ` — ${j.comments_scored}/${j.comments_total} scored`
      : j.comments_collected ? ` — ${j.comments_collected} comments` : "";
    setProgress(j.stage + extra, pct);
    await new Promise((r) => setTimeout(r, 1000));
  }
}

const show = (id, on) => { $(id).hidden = !on; };
const setProgress = (t, p) => { $("stage").textContent = t; $("bar-fill").style.width = p + "%"; };
function showError(msg) { show("progress", false); $("error").textContent = msg; show("error", true); }

// ---- render ----
const view = () => data[scope];
const rowsInScope = () => data.comments.filter((c) => scope === "all" || c.ontopic);

function render() {
  show("results", true);
  if (data.warnings.length) { $("warn").textContent = "Notes: " + data.warnings.join(" · "); show("warn", true); }
  $("meta").textContent = (data.mode === "channel" ? `Channel: ${data.label}` : `“${data.query}” · ${data.region}`) +
    ` · Topics: ${data.pack_label} · ${data.generated_at}`;
  $("export").href = `/api/export.csv?job_id=${jobId}`;
  const topics = Object.keys(data.all.topic_total);
  $("f-topic").innerHTML = '<option value="">All topics</option>' + topics.map((t) => `<option>${t}</option>`).join("");
  renderKpis(); renderCharts(); renderTable();
}

function renderKpis() {
  const v = view();
  if (!v.total) { $("kpis").innerHTML = '<div class="kpi"><div class="v">0</div><div class="l">No comments in this scope</div></div>'; return; }
  const k = (cls, val, label) => `<div class="kpi ${cls}"><div class="v">${val}</div><div class="l">${label}</div></div>`;
  const html =
    k("", v.total.toLocaleString(), "Comments") +
    k("pos", v.percent.Positive + "%", `Positive (${v.counts.Positive})`) +
    k("neu", v.percent.Neutral + "%", `Neutral (${v.counts.Neutral})`) +
    k("neg", v.percent.Negative + "%", `Negative (${v.counts.Negative})`) +
    k("", v.review_required, "Need manual review (<0.60)") +
    (scope === "all" ? k("", data.ontopic.total || 0, "On-topic comments") : "");
  $("kpis").innerHTML = html;
  countUp();
}

// animate numbers (keeps any % / thousands formatting)
function countUp() {
  document.querySelectorAll(".kpi .v").forEach((el) => {
    const m = el.textContent.match(/^([\d,.]+)(%?)$/);
    if (!m || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const end = parseFloat(m[1].replace(/,/g, "")), dec = (m[1].split(".")[1] || "").length, t0 = performance.now();
    const step = (t) => {
      const p = Math.min(1, (t - t0) / 700), e = 1 - Math.pow(1 - p, 3), val = end * e;
      el.textContent = (dec ? val.toFixed(dec) : Math.round(val).toLocaleString()) + m[2];
      if (p < 1) requestAnimationFrame(step); else el.textContent = (dec ? end.toFixed(dec) : Math.round(end).toLocaleString()) + m[2];
    };
    requestAnimationFrame(step);
  });
}

const centerText = { id: "centerText", afterDraw(chart, _a, opts) {
  if (!opts || !opts.text) return;
  const { ctx, chartArea: { left, right, top, bottom } } = chart, x = (left + right) / 2, y = (top + bottom) / 2;
  ctx.save(); ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillStyle = css("--text"); ctx.font = `700 26px ${Chart.defaults.font.family}`; ctx.fillText(opts.text, x, y - 8);
  ctx.fillStyle = css("--muted"); ctx.font = `500 12px ${Chart.defaults.font.family}`; ctx.fillText(opts.sub, x, y + 14);
  ctx.restore();
} };

function mk(id, cfg) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($(id), cfg);
}

function renderCharts() {
  const v = view(), colors = sentColor(), text = css("--text"), grid = css("--grid");
  Chart.defaults.color = css("--muted");
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.plugins.tooltip.backgroundColor = css("--text");
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.animation.duration = 800;
  const base = { responsive: true, maintainAspectRatio: false };
  const axes = (stacked) => ({
    x: { stacked, grid: { color: grid } },
    y: { stacked, beginAtZero: true, grid: { color: grid }, ticks: { precision: 0 } },
  });
  if (!v.total) { Object.values(charts).forEach((c) => c.destroy()); charts = {}; return; }

  mk("c-sent", { type: "doughnut", data: {
      labels: SENT, datasets: [{ data: SENT.map((s) => v.counts[s]), backgroundColor: SENT.map((s) => colors[s]), borderColor: css("--card"), borderWidth: 2 }] },
    options: { ...base, cutout: "68%", plugins: { centerText: { text: v.total.toLocaleString(), sub: "comments" }, legend: { position: "bottom", labels: { color: text, usePointStyle: true, boxWidth: 8 } } } },
    plugins: [centerText] });

  const topics = Object.keys(v.topic_total);
  mk("c-topic", { type: "bar", data: {
      labels: topics, datasets: [{ data: topics.map((t) => v.topic_total[t]), backgroundColor: css("--accent"), borderRadius: 6 }] },
    options: { ...base, plugins: { legend: { display: false } }, scales: axes(false) } });

  mk("c-topic-sent", { type: "bar", data: {
      labels: topics, datasets: SENT.map((s) => ({ label: s, data: topics.map((t) => v.topic_by_sentiment[t][s]), backgroundColor: colors[s] })) },
    options: { ...base, plugins: { legend: { position: "bottom", labels: { color: text } } }, scales: axes(true) } });

  const vids = v.by_video;
  mk("c-video", { type: "bar", data: {
      labels: vids.map((x) => x.title.length > 38 ? x.title.slice(0, 38) + "…" : x.title),
      datasets: SENT.map((s) => ({ label: s, data: vids.map((x) => x[s]), backgroundColor: colors[s] })) },
    options: { ...base, indexAxis: "y", plugins: { legend: { position: "bottom", labels: { color: text } } },
      scales: { x: { stacked: true, grid: { color: grid }, ticks: { precision: 0 } }, y: { stacked: true, grid: { display: false } } } } });

  const words = v.top_words || [];
  mk("c-words", { type: "bar", data: {
      labels: words.map((x) => x.word),
      datasets: SENT.map((s) => ({ label: s, data: words.map((x) => x[s]), backgroundColor: colors[s] })) },
    options: { ...base, indexAxis: "y", plugins: { legend: { position: "bottom", labels: { color: text } } },
      scales: { x: { stacked: true, grid: { color: grid }, ticks: { precision: 0 } }, y: { stacked: true, grid: { display: false } } } } });

  mk("c-conf", { type: "bar", data: {
      labels: v.confidence_hist.map((_, i) => (i / 10).toFixed(1) + "–" + ((i + 1) / 10).toFixed(1)),
      datasets: [{ data: v.confidence_hist, backgroundColor: v.confidence_hist.map((_, i) => i < 6 ? css("--neu") : css("--accent")), borderRadius: 6 }] },
    options: { ...base, plugins: { legend: { display: false } }, scales: axes(false) } });
}

function filtered() {
  const q = $("search").value.trim().toLowerCase(), s = $("f-sent").value, t = $("f-topic").value, r = $("f-review").checked;
  return rowsInScope().filter((c) =>
    (!q || c.text.toLowerCase().includes(q)) && (!s || c.sentiment === s) &&
    (!t || c.topics.includes(t)) && (!r || c.review));
}

const esc = (s) => s.replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));

function renderTable() {
  const rows = filtered(), pages = Math.max(1, Math.ceil(rows.length / PAGE));
  page = Math.min(page, pages - 1);
  $("rows").innerHTML = rows.slice(page * PAGE, (page + 1) * PAGE).map((c) => `
    <tr>
      <td class="text">${esc(c.text)}</td>
      <td><span class="pill ${c.sentiment}">${c.sentiment}</span></td>
      <td>${c.confidence.toFixed(2)}${c.review ? ' <span class="flag" title="Needs manual review">⚑</span>' : ""}</td>
      <td>${c.topics.join(", ") || "–"}</td>
      <td>${c.likes}</td>
      <td><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.video.length > 40 ? c.video.slice(0, 40) + "…" : c.video)}</a></td>
    </tr>`).join("") || '<tr><td colspan="6" class="muted">No comments match.</td></tr>';
  $("page-info").textContent = `${rows.length} comments · page ${page + 1}/${pages}`;
  $("prev").disabled = page === 0;
  $("next").disabled = page >= pages - 1;
}

document.querySelectorAll(".seg button").forEach((b) => b.onclick = () => {
  scope = b.dataset.scope; page = 0;
  document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
  renderKpis(); renderCharts(); renderTable();
});
["search", "f-sent", "f-topic", "f-review"].forEach((id) =>
  $(id).addEventListener(id === "search" ? "input" : "change", () => { page = 0; renderTable(); }));
$("prev").onclick = () => { page--; renderTable(); };
$("next").onclick = () => { page++; renderTable(); };

// mode switch: channel mode takes a channel URL / @handle / name; region and sort only apply to search
function syncMode() {
  const ch = $("mode").value === "channel";
  document.querySelectorAll(".only-search").forEach((el) => { el.hidden = ch; });
  $("q-label").textContent = ch ? "Channel (URL, @handle or name)" : "Search query";
  $("query").placeholder = ch ? "@mkbhd or https://www.youtube.com/@mkbhd" : "e.g. Casio G-Shock review";
}
$("mode").onchange = syncMode;
syncMode();

// example chips on the welcome card
document.querySelectorAll(".chip").forEach((c) => c.onclick = () => {
  $("mode").value = c.dataset.mode; syncMode(); $("query").value = c.dataset.q;
  $("form").requestSubmit();
});
