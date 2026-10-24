"""Cleaning, on-topic filter, topic packs and aggregation (notebook cells 18, 31, 36, generalised)."""
import re
from collections import Counter

import pandas as pd

SENTIMENTS = ["Positive", "Neutral", "Negative"]

# Topic packs. "clothing" is the notebook's original keyword set; the others make the
# dashboard useful for any subject. `filter` decides what counts as "on-topic".
PACKS = {
    "clothing": {
        "label": "Clothing & fashion",
        "triggers": ["cloth", "dress", "suit", "fashion", "eid", "lawn", "kurta", "kurti", "shalwar",
                     "wear", "outfit", "boutique", "stitch", "fabric", "khaddar", "collection"],
        "topics": {
            "Price": ["price", "mehnga", "sasta", "kitne ka", "expensive"],
            "Quality": ["quality", "fabric", "kapra", "stitching"],
            "Design": ["design", "pyara", "zabardast", "beautiful", "colour", "color"],
            "Delivery": ["delivery", "shipping", "parcel", "order"],
            "Availability": ["available", "kahan mil", "size", "stock"],
        },
        "filter": ["price", "dress", "suit", "kapra", "quality", "delivery", "size", "design",
                   "fabric", "colour", "price kya", "kitne ka", "kahan mil"],
    },
    "watches": {
        "label": "Watches",
        "triggers": ["watch", "casio", "rolex", "seiko", "g-shock", "gshock", "citizen", "timex",
                     "omega", "tissot", "chronograph", "smartwatch", "apple watch", "garmin", "fossil"],
        "topics": {
            "Price": ["price", "cost", "expensive", "cheap", "worth", "afford", "value", "mehnga", "sasta"],
            "Build quality": ["quality", "build", "strap", "band", "glass", "sapphire", "scratch", "durable", "material"],
            "Design": ["design", "look", "looks", "style", "dial", "case", "color", "colour", "beautiful"],
            "Accuracy & battery": ["accuracy", "accurate", "battery", "movement", "automatic", "quartz", "solar"],
            "Authenticity & service": ["fake", "original", "authentic", "warranty", "service", "delivery", "shipping"],
        },
        "filter": [],  # filled below from topics
    },
    "electronics": {
        "label": "Phones & electronics",
        "triggers": ["phone", "iphone", "samsung", "laptop", "camera", "headphone", "earbuds", "tv",
                     "gadget", "android", "pixel", "tablet", "console", "ps5", "gpu", "pc ", "speaker"],
        "topics": {
            "Price": ["price", "cost", "expensive", "cheap", "worth", "afford", "value", "mehnga", "sasta"],
            "Performance": ["performance", "fast", "slow", "speed", "lag", "smooth", "fps", "processor"],
            "Battery": ["battery", "charging", "charge", "backup"],
            "Camera & display": ["camera", "display", "screen", "photo", "video quality", "resolution"],
            "Build & design": ["build", "design", "quality", "look", "heavy", "plastic", "metal"],
        },
        "filter": [],
    },
    "general": {
        "label": "General (any subject)",
        "triggers": [],
        "topics": {
            "Price & value": ["price", "cost", "expensive", "cheap", "worth", "afford", "value", "mehnga", "sasta", "paisa"],
            "Quality": ["quality", "build", "durable", "material", "broken", "defect", "reliable"],
            "Performance": ["performance", "fast", "slow", "speed", "works", "battery", "accurate"],
            "Design & looks": ["design", "look", "looks", "style", "beautiful", "color", "colour", "pyara"],
            "Service & delivery": ["delivery", "shipping", "support", "warranty", "refund", "service", "order"],
            "Content & creator": ["video", "content", "explain", "voice", "editing", "music", "channel", "subscribe"],
        },
        "filter": [],
    },
}
for _p in PACKS.values():
    if not _p["filter"]:
        _p["filter"] = sorted({w for ws in _p["topics"].values() for w in ws})


def _compile(words):
    # word-start boundary, so "price" matches "prices" but "tv" does not match "button"
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in words) + ")", re.IGNORECASE)


for _p in PACKS.values():
    _p["filter_re"] = _compile(_p["filter"])
    _p["topic_re"] = {t: _compile(ws) for t, ws in _p["topics"].items()}


def pick_pack(query, requested="auto"):
    if requested in PACKS:
        return requested
    q = (query or "").lower()
    scores = {k: sum(t in q for t in p["triggers"]) for k, p in PACKS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def clean(df):
    df = df.dropna(subset=["comment_text"]).copy()
    df["comment_text"] = df["comment_text"].astype(str).str.strip()
    df = df[df["comment_text"] != ""]
    return df.drop_duplicates(subset=["video_id", "comment_text"]).reset_index(drop=True)


def is_on_topic(text, pack):
    return bool(PACKS[pack]["filter_re"].search(text or ""))


def topics_for(text, pack):
    t = text or ""
    return [name for name, rx in PACKS[pack]["topic_re"].items() if rx.search(t)]


STOP = set("""
the and for are but not you your with this that have has had was were from they them their what when
who why how all any can will just about would could should there here then than too very more most
some such into out over also its it's i'm im ive dont don't didn't cant can't get got one like love
video videos watch watching please these those still never thing way now see see even much many really thanks thank sir bro bhai plz pls
hai hain hy hn ha ka ki ke ko se me mein main may ye yeh wo woh or aur bhi nahi nhi kya kaun kis kab
kahan kyun tha thi the hoga hogi ho hoon hun tum tu aap apna apni apne mera meri mere tera teri hum
bohat bahut boht bht bhot kuch sab sirf bas par per pe lekin magar agar toh to ab abhi jo jis uska
uski iska iski wala wali wale kar kia kiya karo karna kro krna hota hoti hote raha rahi rahe
""".split())
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def top_words(df, n=15, exclude=frozenset()):
    """Most frequent meaningful words with their sentiment split."""
    total, by = Counter(), {s: Counter() for s in SENTIMENTS}
    for text, sent in zip(df["comment_text"], df["predicted_sentiment"]):
        for w in set(_WORD.findall(text.lower())):
            if w in STOP or w in exclude:
                continue
            total[w] += 1
            if sent in by:
                by[sent][w] += 1
    return [{"word": w, "total": c, **{s: by[s][w] for s in SENTIMENTS}}
            for w, c in total.most_common(n) if c >= 2]


def _counts(series):
    vc = series.value_counts()
    return {s: int(vc.get(s, 0)) for s in SENTIMENTS}


def summarize(df, pack, query=""):
    """Aggregate a scored dataframe (with a `topics` column) into dashboard numbers."""
    total = len(df)
    if total == 0:
        return {"total": 0}

    counts = _counts(df["predicted_sentiment"])
    names = list(PACKS[pack]["topics"])
    topic_total = {t: 0 for t in names}
    topic_by_sent = {t: {s: 0 for s in SENTIMENTS} for t in names}
    for topics, sent in zip(df["topics"], df["predicted_sentiment"]):
        for t in topics:
            topic_total[t] += 1
            if sent in topic_by_sent[t]:
                topic_by_sent[t][sent] += 1

    by_video = []
    for (vid, title), g in df.groupby(["video_id", "video_title"], sort=False):
        by_video.append({"video_id": vid, "title": title, "total": len(g),
                         **_counts(g["predicted_sentiment"])})

    hist = [0] * 10  # confidence buckets 0.0-0.1 ... 0.9-1.0
    for c in df["confidence"]:
        hist[min(int(c * 10), 9)] += 1

    return {
        "total": total,
        "counts": counts,
        "percent": {s: round(counts[s] / total * 100, 1) for s in SENTIMENTS},
        "review_required": int(df["review_required"].sum()),
        "topic_total": topic_total,
        "topic_by_sentiment": topic_by_sent,
        "by_video": by_video,
        "confidence_hist": hist,
        "top_words": top_words(df, exclude=set(_WORD.findall((query or "").lower()))),
    }
