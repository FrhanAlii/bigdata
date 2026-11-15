# Comment Sentiment Dashboard

Live dashboard version of `project 1.ipynb`: searches YouTube, collects comments, scores sentiment with
`cardiffnlp/xlm-roberta-base-sentiment-multilingual`, and shows sentiment, clothing-related filtering and topic charts.

## Run
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then put your YouTube Data API v3 key in .env
uvicorn app.main:app --reload
```
Open http://localhost:8000. The first analysis downloads the model (~1 GB); later runs are fast.
Results for the same query are cached for 30 minutes to save YouTube quota (one run is roughly 1,100 units of the 10,000/day free quota).

## Tests
`pytest`

## Using it
- **Search videos** mode: any query (e.g. `Casio G-Shock watch review`), with region and sort order (relevance, most viewed, newest, top rated).
- **Channel** mode: a channel URL, `@handle`, channel id (`UC...`) or plain name. Analyses the channel's latest videos.
- **Topics**: auto-detected from the query (clothing, watches, phones & electronics, general) or chosen manually. Edit the packs in `app/analysis.py` to add your own.
- "On-topic only" keeps comments that match the selected topic pack's keywords.

## Budget optimizer
After an analysis finishes, use the **Budget optimizer** card: enter a budget, currency (PKR/USD/GBP/EUR) and goal
(sales/awareness/engagement). The comments' sentiment mood (positive/mixed/negative), the topic pack and the goal are
scored against 7 ad platforms; the budget is split across the best 2-4 (max 60% each, split sums exactly to your
budget), with a campaign suggestion, estimated impressions, a test/scale/retarget plan and risks (e.g. topics with many
negative comments). Logic is in `app/budget.py` (`POST /api/budget`). Figures are planning estimates, not guarantees.
