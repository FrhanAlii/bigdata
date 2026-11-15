"""Budget optimizer: turns a finished sentiment analysis + a budget into a multi-platform ad split.

Everything here is a deterministic heuristic (no ML, no network). Platform numbers are rough
benchmarks meant for planning, not guarantees.
"""

MOODS = ("positive", "mixed", "negative")
GOALS = ("awareness", "sales", "engagement")
CURRENCIES = {"PKR": 280.0, "USD": 1.0, "GBP": 0.79, "EUR": 0.92}  # units per 1 USD (approx.)

MAX_SHARE = 0.60       # no platform gets more than this
MIN_SHARE = 0.10       # platforms that would get less are dropped (down to 2)
MAX_PLATFORMS = 4
MIN_PLATFORMS = 2

# fit: audience fit per topic pack (0-1). mood: how well it suits each sentiment mood.
# goal: how well it serves each campaign goal. cpm: approx USD per 1,000 impressions.
PLATFORMS = {
    "youtube": {
        "label": "YouTube Ads", "cpm": 6.0, "campaign": "In-stream + Shorts video ads",
        "fit": {"clothing": .75, "watches": .90, "electronics": .95, "general": .80},
        "mood": {"positive": .90, "mixed": .75, "negative": .50},
        "goal": {"awareness": .95, "sales": .65, "engagement": .75},
        "why": "Reaches the same video-watching audience that produced these comments.",
    },
    "meta": {
        "label": "Meta (Instagram + Facebook)", "cpm": 5.0, "campaign": "Reels + carousel catalogue ads",
        "fit": {"clothing": 1.0, "watches": .80, "electronics": .70, "general": .80},
        "mood": {"positive": .90, "mixed": .80, "negative": .60},
        "goal": {"awareness": .85, "sales": .90, "engagement": .90},
        "why": "Strong visual shopping format with precise interest and lookalike targeting.",
    },
    "tiktok": {
        "label": "TikTok Ads", "cpm": 4.0, "campaign": "Spark Ads boosting creator videos",
        "fit": {"clothing": .90, "watches": .60, "electronics": .65, "general": .70},
        "mood": {"positive": 1.0, "mixed": .65, "negative": .30},
        "goal": {"awareness": 1.0, "sales": .60, "engagement": 1.0},
        "why": "Cheap reach that rewards the positive buzz; best when sentiment is warm.",
    },
    "google_search": {
        "label": "Google Search Ads", "cpm": 12.0, "campaign": "Brand + high-intent keyword search",
        "fit": {"clothing": .60, "watches": .80, "electronics": .90, "general": .75},
        "mood": {"positive": .65, "mixed": .85, "negative": .90},
        "goal": {"awareness": .35, "sales": 1.0, "engagement": .30},
        "why": "Captures people already searching, and lets you answer doubts with your own message.",
    },
    "snapchat": {
        "label": "Snapchat Ads", "cpm": 4.5, "campaign": "Story ads + AR lens",
        "fit": {"clothing": .70, "watches": .40, "electronics": .50, "general": .50},
        "mood": {"positive": .80, "mixed": .55, "negative": .30},
        "goal": {"awareness": .80, "sales": .50, "engagement": .75},
        "why": "Young audience, inexpensive impressions, good for launches.",
    },
    "linkedin": {
        "label": "LinkedIn Ads", "cpm": 30.0, "campaign": "Sponsored content to professionals",
        "fit": {"clothing": .10, "watches": .40, "electronics": .50, "general": .35},
        "mood": {"positive": .60, "mixed": .65, "negative": .60},
        "goal": {"awareness": .50, "sales": .50, "engagement": .40},
        "why": "Premium, professional audience; only worth it for higher-ticket products.",
    },
    "x": {
        "label": "X (Twitter) Ads", "cpm": 6.5, "campaign": "Promoted posts + conversation targeting",
        "fit": {"clothing": .30, "watches": .45, "electronics": .70, "general": .50},
        "mood": {"positive": .60, "mixed": .55, "negative": .20},
        "goal": {"awareness": .65, "sales": .40, "engagement": .65},
        "why": "Reaches people discussing the topic; risky when sentiment is negative.",
    },
}

MOOD_ADVICE = {
    "positive": "Audience sentiment is warm, so lean into reach and social proof: scale the platforms where people can see and share.",
    "mixed": "Sentiment is divided, so balance reach with intent: split between discovery platforms and search/retargeting, and test messages.",
    "negative": "Sentiment is mostly negative, so avoid broad-reach spending. Favour intent/search and controlled channels, and fix the top complaint before scaling.",
}


def sentiment_profile(result):
    """Boil a finished job `result` down to what the optimizer needs."""
    on = result.get("ontopic") or {}
    all_ = result.get("all") or {}
    summary = on if on.get("total", 0) >= 20 else all_
    total = summary.get("total", 0)
    if not total:
        raise ValueError("No comments to base a strategy on.")
    pct = summary["percent"]
    if pct["Positive"] >= 55:
        mood = "positive"
    elif pct["Negative"] >= 35:
        mood = "negative"
    else:
        mood = "mixed"

    tbs = summary.get("topic_by_sentiment", {})
    topics = []
    for name, n in (summary.get("topic_total") or {}).items():
        if n:
            neg = tbs.get(name, {}).get("Negative", 0)
            topics.append({"topic": name, "mentions": n, "negative_pct": round(neg / n * 100, 1)})
    topics.sort(key=lambda t: -t["mentions"])
    return {"mood": mood, "total": total, "percent": pct, "topics": topics,
            "scope": "on-topic" if summary is on else "all"}


def _water_fill(scores):
    """Proportional shares (sum 1) with no share above MAX_SHARE; excess goes to the others."""
    shares = {k: 0.0 for k in scores}
    free, left = dict(scores), 1.0
    while free:
        tot = sum(free.values())
        over = [k for k, s in free.items() if left * s / tot > MAX_SHARE + 1e-12]
        if not over:
            for k, s in free.items():
                shares[k] = left * s / tot
            break
        for k in over:
            shares[k] = MAX_SHARE
            left -= MAX_SHARE
            del free[k]
    return shares


def _split_cents(shares, cents):
    """Largest-remainder rounding so the parts add up to exactly `cents`."""
    raw = {k: s * cents for k, s in shares.items()}
    out = {k: int(v) for k, v in raw.items()}
    rest = cents - sum(out.values())
    for k in sorted(raw, key=lambda k: (-(raw[k] - out[k]), k))[:rest]:
        out[k] += 1
    return out


def optimize(profile, pack, budget, currency="PKR", goal="sales"):
    if currency not in CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency}")
    if goal not in GOALS:
        raise ValueError(f"Unsupported goal: {goal}")
    cents = int(round(float(budget) * 100))
    if cents < 2:
        raise ValueError("Budget is too small to split across two platforms.")
    mood = profile["mood"]
    pack = pack if pack in PLATFORMS["meta"]["fit"] else "general"

    scores = {k: p["fit"][pack] * p["mood"][mood] * p["goal"][goal] for k, p in PLATFORMS.items()}
    chosen = sorted(scores, key=lambda k: (-scores[k], k))[:MAX_PLATFORMS]
    while True:
        shares = _water_fill({k: scores[k] for k in chosen})
        smallest = min(chosen, key=lambda k: shares[k])
        if len(chosen) > MIN_PLATFORMS and shares[smallest] < MIN_SHARE:
            chosen.remove(smallest)
        else:
            break
    amounts = _split_cents(shares, cents)

    usd_per_unit = 1 / CURRENCIES[currency]
    allocation = []
    for k in sorted(chosen, key=lambda k: -amounts[k]):
        p = PLATFORMS[k]
        amount = amounts[k] / 100
        allocation.append({
            "platform": k, "label": p["label"], "amount": amount,
            "percent": round(amounts[k] / cents * 100, 1),
            "campaign": p["campaign"], "why": p["why"],
            "est_impressions": int(amount * usd_per_unit / p["cpm"] * 1000),
        })

    risks = []
    worst = [t for t in profile["topics"] if t["mentions"] >= 3 and t["negative_pct"] >= 35]
    for t in sorted(worst, key=lambda t: -t["negative_pct"])[:2]:
        risks.append(f'"{t["topic"]}" draws {t["negative_pct"]}% negative mentions; address it in ad copy or fix it before scaling.')
    if mood == "negative":
        risks.append("High share of negative comments: expect lower conversion on cold audiences.")
    if profile["total"] < 100:
        risks.append(f'Only {profile["total"]} comments analysed; run a larger analysis for a firmer strategy.')

    return {
        "mood": mood, "scope": profile["scope"], "sentiment": profile["percent"],
        "currency": currency, "goal": goal, "budget": cents / 100,
        "headline": MOOD_ADVICE[mood],
        "allocation": allocation,
        "phases": [
            {"name": "Test", "percent": 20, "amount": round(cents * 0.20) / 100,
             "detail": "Run all chosen platforms with 2-3 creatives; watch cost per result for a week."},
            {"name": "Scale", "percent": 50, "amount": round(cents * 0.50) / 100,
             "detail": "Move spend to the best-performing platform and creative."},
            {"name": "Retarget", "percent": 30, "amount": cents / 100 - round(cents * 0.20) / 100 - round(cents * 0.50) / 100,
             "detail": "Retarget viewers and visitors with proof-focused messages."},
        ],
        "risks": risks,
        "note": "Impressions are rough estimates from typical CPMs; real results vary by creative, audience and season.",
    }
