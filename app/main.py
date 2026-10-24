import csv
import io
from typing import Literal
import threading
import time
import uuid
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from . import analysis, sentiment, youtube  # noqa: E402  (after load_dotenv)

STATIC = Path(__file__).resolve().parent.parent / "static"
CACHE_TTL = 60 * 30

app = FastAPI(title="Comment Sentiment Dashboard")
jobs = {}
cache = {}  # (query, region, max_videos, max_comments) -> (timestamp, job_id)


class AnalyzeRequest(BaseModel):
    mode: Literal["search", "channel"] = "search"
    query: str = Field("Pakistani clothing brand Eid collection", min_length=1, max_length=200)
    region: str = Field("PK", min_length=2, max_length=2)
    order: Literal["relevance", "date", "viewCount", "rating"] = "relevance"
    pack: Literal["auto", "clothing", "watches", "electronics", "general"] = "auto"
    max_videos: int = Field(10, ge=1, le=25)
    max_comments: int = Field(100, ge=10, le=300)
    refresh: bool = False


def _key(req):
    return (req.mode, req.query.strip().lower(), req.region.upper(), req.order, req.pack,
            req.max_videos, req.max_comments)


def _run(job_id, req):
    job = jobs[job_id]
    try:
        job.update(status="running", stage="Searching videos")
        yt = youtube.get_client()
        pack = analysis.pick_pack(req.query, req.pack)
        label = req.query
        if req.mode == "channel":
            job["stage"] = "Finding channel"
            channel = youtube.resolve_channel(yt, req.query)
            label = channel["title"]
            job["stage"] = f"Loading latest videos from {label}"
            videos = youtube.list_channel_videos(yt, channel, req.max_videos)
        else:
            videos = youtube.search_videos(yt, req.query, req.region.upper(), req.max_videos, req.order)
        if not videos:
            raise RuntimeError("No videos found for this query.")
        job["videos_total"] = len(videos)

        rows, warnings = [], []
        for i, v in enumerate(videos, 1):
            job.update(stage=f"Collecting comments ({i}/{len(videos)})", videos_done=i - 1)
            comments, err = youtube.get_comments(yt, v["video_id"], req.max_comments)
            if err and not comments:
                warnings.append(f'"{v["title"][:50]}": no comments ({err.splitlines()[0][:80]})')
            for c in comments:
                rows.append({**c, "video_title": v["title"], "channel": v["channel"],
                             "video_url": v["video_url"]})
            job["comments_collected"] = len(rows)
        job["videos_done"] = len(videos)

        df = analysis.clean(pd.DataFrame(rows)) if rows else pd.DataFrame()
        if df.empty:
            raise RuntimeError("No comments found. Try a different query.")
        job.update(comments_total=len(df), comments_scored=0, stage="Scoring sentiment (first run downloads the model)")

        preds = sentiment.predict(df["comment_text"].tolist(),
                                  on_progress=lambda n: job.update(comments_scored=n, stage="Scoring sentiment"))
        df["predicted_sentiment"] = [p[0] for p in preds]
        df["confidence"] = [p[1] for p in preds]
        df["review_required"] = df["confidence"] < sentiment.REVIEW_THRESHOLD
        df["on_topic"] = df["comment_text"].map(lambda t: analysis.is_on_topic(t, pack))
        df["topics"] = df["comment_text"].map(lambda t: analysis.topics_for(t, pack))

        on_topic = df[df["on_topic"]]
        job["df"] = df
        job["result"] = {
            "query": req.query,
            "mode": req.mode,
            "label": label,
            "pack": pack,
            "pack_label": analysis.PACKS[pack]["label"],
            "region": req.region.upper() if req.mode == "search" else "-",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "warnings": warnings,
            "all": analysis.summarize(df, pack, req.query),
            "ontopic": analysis.summarize(on_topic, pack, req.query),
            "comments": [
                {
                    "text": r.comment_text, "sentiment": r.predicted_sentiment,
                    "confidence": r.confidence, "review": bool(r.review_required),
                    "ontopic": bool(r.on_topic), "topics": r.topics,
                    "likes": int(r.like_count), "video": r.video_title,
                    "url": r.video_url, "date": r.published_at,
                }
                for r in df.itertuples()
            ],
        }
        job.update(status="done", stage="Done")
        cache[_key(req)] = (time.time(), job_id)
    except Exception as e:
        job.update(status="error", error=str(e), stage="Failed")


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    hit = cache.get(_key(req))
    if hit and not req.refresh and time.time() - hit[0] < CACHE_TTL and jobs.get(hit[1], {}).get("status") == "done":
        return {"job_id": hit[1], "cached": True}

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"status": "queued", "stage": "Queued", "videos_total": 0, "videos_done": 0,
                    "comments_collected": 0, "comments_total": 0, "comments_scored": 0}
    threading.Thread(target=_run, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id, "cached": False}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return {k: v for k, v in job.items() if k != "df"}


@app.get("/api/export.csv")
def export_csv(job_id: str):
    job = jobs.get(job_id)
    if not job or "df" not in job:
        raise HTTPException(404, "No finished job with that id")
    buf = io.StringIO()
    out = job["df"].drop(columns=["topics"]).copy()
    out["topics"] = job["df"]["topics"].map(", ".join)
    out.to_csv(buf, index=False, quoting=csv.QUOTE_NONNUMERIC)
    return Response(
        ("﻿" + buf.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=comment_sentiment_results.csv"},
    )


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
