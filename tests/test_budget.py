import pytest
from fastapi.testclient import TestClient

from app import budget, main


def summary(pos, neu, neg, total=200):
    return {"total": total, "percent": {"Positive": pos, "Neutral": neu, "Negative": neg},
            "topic_total": {"Price": 40, "Quality": 10},
            "topic_by_sentiment": {"Price": {"Positive": 5, "Neutral": 5, "Negative": 30},
                                   "Quality": {"Positive": 8, "Neutral": 1, "Negative": 1}}}


def plan(pos, neu, neg, amount=100000, pack="clothing", goal="sales", cur="PKR"):
    prof = budget.sentiment_profile({"all": summary(pos, neu, neg), "ontopic": {"total": 0}})
    return budget.optimize(prof, pack, amount, cur, goal)


def test_moods():
    assert plan(70, 20, 10)["mood"] == "positive"
    assert plan(40, 30, 30)["mood"] == "mixed"
    assert plan(20, 30, 50)["mood"] == "negative"


@pytest.mark.parametrize("amount", [100000, 1000 / 3, 0.07, 999.99, 2, 1e9])
@pytest.mark.parametrize("mood", [(70, 20, 10), (40, 30, 30), (20, 30, 50)])
@pytest.mark.parametrize("pack", ["clothing", "watches", "electronics", "general"])
@pytest.mark.parametrize("goal", ["awareness", "sales", "engagement"])
def test_split_exact_and_valid(amount, mood, pack, goal):
    p = plan(*mood, amount=amount, pack=pack, goal=goal)
    cents = round(amount * 100)
    assert sum(round(a["amount"] * 100) for a in p["allocation"]) == cents
    assert 2 <= len(p["allocation"]) <= 4
    assert all(a["percent"] <= 60.1 or cents < 100 for a in p["allocation"])
    assert abs(sum(x["amount"] for x in p["phases"]) - p["budget"]) < 0.005


def test_strategy_changes_with_sentiment():
    pos = plan(70, 20, 10, goal="awareness")["allocation"][0]["platform"]
    neg = plan(20, 30, 50, goal="sales")["allocation"][0]["platform"]
    assert pos != neg
    assert neg == "google_search"


def test_risks_flag_negative_topic():
    assert any("Price" in r for r in plan(40, 30, 30)["risks"])


def test_invalid_inputs():
    prof = budget.sentiment_profile({"all": summary(50, 30, 20)})
    with pytest.raises(ValueError):
        budget.optimize(prof, "general", 0.01)
    with pytest.raises(ValueError):
        budget.optimize(prof, "general", 100, "XXX")
    with pytest.raises(ValueError):
        budget.sentiment_profile({"all": {"total": 0}})


def test_api_route():
    c = TestClient(main.app)
    main.jobs["t1"] = {"status": "done", "result": {"pack": "watches", "all": summary(60, 25, 15), "ontopic": {"total": 0}}}
    r = c.post("/api/budget", json={"job_id": "t1", "budget": 5000, "currency": "USD", "goal": "sales"})
    assert r.status_code == 200 and sum(a["amount"] for a in r.json()["allocation"]) == pytest.approx(5000)
    assert c.post("/api/budget", json={"job_id": "nope", "budget": 5}).status_code == 404
    assert c.post("/api/budget", json={"job_id": "t1", "budget": -5}).status_code == 422
    main.jobs["t2"] = {"status": "done", "result": {"pack": "general", "all": {"total": 0}}}
    assert c.post("/api/budget", json={"job_id": "t2", "budget": 50}).status_code == 422
