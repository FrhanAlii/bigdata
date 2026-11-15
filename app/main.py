import csv
import io
from typing import Literal
import threading
import time
import uuid
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analysis, budget, sentiment

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Comment Sentiment Dashboard")
jobs = {}


class CommentRow(BaseModel):
    video_id: str
    comment_text: str
    published_at: str
    like_count: int = 0
    video_title: str
    channel: str
    video_url: str


class AnalyzeRequest(BaseModel):
    mode: Literal["search", "channel"] = "search"
    query: str = Field("Pakistani clothing brand Eid collection", min_length=1, max_length=200)
    region: str = Field("PK", min_length=2, max_length=2)
    order: Literal["relevance", "date", "viewCount", "rating"] = "relevance"
    pack: Literal["auto", "clothing", "watches", "electronics", "general"] = "auto"
    max_videos: int = Field(10, ge=1, le=25)
    max_comments: int = Field(100, ge=10, le=300)
    label: str = Field("", max_length=200)
    warnings: list[str] = []
    rows: list[CommentRow] = Field(..., min_length=1, max_length=25 * 300)


def _run(job_id, req):
    job = jobs[job_id]
    try:
        job.update(status="running", stage="Preparing comments")
        pack = analysis.pick_pack(req.query, req.pack)
        label = req.label or req.query
        warnings = list(req.warnings)
        rows = [r.model_dump() for r in req.rows]

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
    except Exception as e:
        job.update(status="error", error=str(e), stage="Failed")


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
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


class BudgetRequest(BaseModel):
    job_id: str
    budget: float = Field(..., gt=0, le=1e9)
    currency: Literal["PKR", "USD", "GBP", "EUR"] = "PKR"
    goal: Literal["awareness", "sales", "engagement"] = "sales"


@app.post("/api/budget")
def plan_budget(req: BudgetRequest):
    job = jobs.get(req.job_id)
    if not job or job.get("status") != "done" or "result" not in job:
        raise HTTPException(404, "No finished analysis with that id")
    try:
        profile = budget.sentiment_profile(job["result"])
        return budget.optimize(profile, job["result"]["pack"], req.budget, req.currency, req.goal)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
