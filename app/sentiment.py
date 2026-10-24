"""Multilingual sentiment, ported from notebook cell 26."""
import os
import threading

# transformers otherwise spawns a background safetensors-conversion download that blocks shutdown
os.environ.setdefault("DISABLE_SAFETENSORS_CONVERSION", "1")

MODEL_NAME = "cardiffnlp/xlm-roberta-base-sentiment-multilingual"
BATCH_SIZE = 16
REVIEW_THRESHOLD = 0.60

LABEL_MAP = {
    "LABEL_0": "Negative",
    "LABEL_1": "Neutral",
    "LABEL_2": "Positive",
    "negative": "Negative",
    "neutral": "Neutral",
    "positive": "Positive",
}

_pipe = None
_lock = threading.Lock()


def _get_pipeline():
    global _pipe
    with _lock:
        if _pipe is None:
            import torch
            from transformers import pipeline

            device = 0 if torch.cuda.is_available() else -1
            _pipe = pipeline(
                "text-classification", model=MODEL_NAME, device=device,
            )
        return _pipe


def predict(texts, on_progress=None):
    """Return [(label, confidence)] for each text, in batches of 16."""
    pipe = _get_pipeline()
    out = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        for r in pipe(batch, batch_size=BATCH_SIZE, truncation=True, max_length=128):
            out.append((LABEL_MAP.get(r["label"], r["label"]), round(float(r["score"]), 4)))
        if on_progress:
            on_progress(len(out))
    return out
