# Superstore Sales Dashboard

An interactive web dashboard built on the Sample Superstore dataset (9,994 order lines, 2014-2017, US retail).
Python (pandas/NumPy) cleans and analyses the data; Flask serves it as a JSON API; Chart.js draws the charts.

## Dataset context
Each row is one product on one order: customer, location, category, `Sales`, `Quantity`, `Discount`, `Profit`.
The business question the dashboard answers: **where does the company make and lose money, and how much does discounting contribute?**

## Pipeline
```
data/raw/*.csv  ->  pipeline/cleaning.py  ->  data/processed/superstore_clean.csv
                                           ->  data/processed/cleaning_report.json
                    pipeline/analytics.py ->  data/processed/summary.json
                                           ->  Flask /api/*  ->  static/js/dashboard.js (Chart.js)
```

### Transformation methodology
**Cleaning (`pipeline/cleaning.py`)** - each step is counted in `cleaning_report.json`:
1. Encoding fallback (UTF-8, then Latin-1; the raw file is Latin-1) and required-column validation.
2. Trim whitespace in text columns; remove exact duplicates and repeated `Row ID`s.
3. Parse `m/d/yyyy` dates; drop unparseable rows.
4. Coerce numeric columns; drop non-numeric rows.
5. Business rules: `Sales > 0`, `Quantity > 0`, `0 <= Discount <= 1`, `Ship Date >= Order Date`.
6. Restore 5-digit postal codes (leading zeros are lost when read as integers).
7. Derived fields: `Year`, `Month`, `Quarter`, `YearMonth`, `ShipDays`, `ProfitMargin`, `IsLoss`, `DiscountBand`.

(This copy of the dataset was already clean, so no rows are removed. The checks exist to protect against bad input.)

**Analysis (`pipeline/analytics.py`):**
- KPIs: sales, profit, margin (profit / sales), orders, customers, average order value, ship time, share of loss-making lines, year-over-year growth.
- Monthly trend with a 3-month moving average and a least-squares linear trend (`numpy.polyfit`).
- Margin by discount band, to test whether heavy discounting destroys profit.
- Outlier detection with the **modified z-score** (median / MAD) per sub-category. Robust to the heavy-tailed profit distribution; flagged when |z| > 3.5.
- Auto-generated plain-language insights that update with the filters.

## Setup and launch
Requires Python 3.10+.
```bash
pip install -r requirements.txt
python run_pipeline.py     # optional: app.py runs it automatically if processed data is missing
python app.py              # open http://127.0.0.1:5000
```
Chart.js and the Manrope font load from CDNs, so an internet connection is needed in the browser.

## Using the dashboard
- **Filters (left):** years, region, category, segment. Every chart, figure and insight recalculates.
- **Sales / Profit / Units toggle:** changes the measure in the trend and breakdown charts.
- **Group by:** break the measure down by category, sub-category, region, segment, ship mode or top-10 states.
- **Tooltips:** hover any chart for exact values, margins and order counts. Loss-making bars are red.

## API
| Endpoint | Purpose |
|---|---|
| `GET /api/filters` | Available years, regions, categories, segments |
| `GET /api/dashboard?years=2016,2017&regions=West&categories=&segments=&metric=profit&dim=state` | All figures and chart data for the current filters |
| `GET /api/health` | Row count / liveness |

Invalid parameters return HTTP 400 with `{"error": "..."}`; the page shows the message instead of failing silently.

## Project layout
```
app.py                 Flask app (routes, validation, error handlers)
run_pipeline.py        CLI that produces data/processed/*
pipeline/cleaning.py   ingestion, validation, feature engineering
pipeline/analytics.py  filters, KPIs, trend, breakdowns, statistics, insights
templates/index.html   page structure
static/css/style.css   responsive layout
static/js/dashboard.js filter state, API calls, Chart.js rendering
data/raw, data/processed
```
