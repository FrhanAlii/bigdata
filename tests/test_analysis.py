import pandas as pd

from app import analysis


def test_topics_and_filter():
    assert analysis.topics_for("Price kya hai? quality zabardast", "clothing") == ["Price", "Quality", "Design"]
    assert analysis.is_on_topic("kahan mil sakta hai", "clothing")
    assert not analysis.is_on_topic("great song", "clothing")
    assert "Accuracy & battery" in analysis.topics_for("battery life is great", "watches")
    assert analysis.topics_for("button", "electronics") == []  # word-start match only


def test_pick_pack():
    assert analysis.pick_pack("Casio G-Shock review") == "watches"
    assert analysis.pick_pack("Eid lawn collection") == "clothing"
    assert analysis.pick_pack("random cooking show") == "general"
    assert analysis.pick_pack("anything", "electronics") == "electronics"


def test_clean_dedupes_and_drops_empty():
    df = pd.DataFrame({"video_id": ["a", "a", "a", "b"], "comment_text": ["nice dress", " nice dress ", "   ", None]})
    assert len(analysis.clean(df)) == 1


def test_summarize():
    texts = ["nice design", "bad quality", "ok"]
    df = pd.DataFrame({
        "video_id": ["a", "a", "b"], "video_title": ["A", "A", "B"], "comment_text": texts,
        "predicted_sentiment": ["Positive", "Negative", "Neutral"],
        "confidence": [0.95, 0.5, 0.7], "review_required": [False, True, False],
        "topics": [analysis.topics_for(t, "clothing") for t in texts],
    })
    s = analysis.summarize(df, "clothing")
    assert s["total"] == 3 and s["counts"]["Negative"] == 1
    assert s["review_required"] == 1
    assert s["topic_by_sentiment"]["Design"]["Positive"] == 1
    assert sum(s["confidence_hist"]) == 3
    assert analysis.summarize(df.iloc[0:0], "clothing")["total"] == 0
