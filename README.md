# TradingView screeners → Google Sheets → email

Small Python service: run TradingView scanner queries, log results to Google Sheets, email an HTML summary. Intended for **Railway cron** (run once, exit).

## Your TradingView screeners vs this script

**This app does not open your saved TradingView screeners** (no link, no login, no “import from my account”). The stock screener you built in the TradingView UI lives in your browser session; TradingView does not give this Python library a simple “fetch screener ID xyz” URL the way you might expect.

What happens instead:

- Each “screener” in this repo is a **Python function** in [`src/screeners.py`](src/screeners.py) that builds a **`Query()`** (market, `.where(...)` filters, `.select(...)` columns, `.order_by`, `.limit`).
- This project includes **Big Volume**, **10% Up**, **Weekly 20% Gainers**, and **Pullback in strong trend**, defined in code to mirror your TradingView rules (still not loaded from the website).

**How to add or tweak a screener:**

1. In TradingView, **write down every rule** for the new idea.
2. Map each rule to a **field name** in the [stock field list](https://shner-elmo.github.io/TradingView-Screener/fields/stocks.html).
3. In `src/screeners.py`, add a function (copy an existing one) with `.set_markets(...)`, `.where(...)`, `.select(...)`, etc.
4. In [`src/run.py`](src/run.py), append it to **`SCREENER_REGISTRY`**.

If you need the **exact** same results as a complex saved layout and the API fields are not enough, the alternative is heavier: **browser automation** (e.g. Playwright) logged into TradingView — that was explicitly out of scope for v1 of this project.

## Setup

Use **Python 3.9+** locally (the Docker image uses 3.12; **3.10+** is recommended when you can install it).

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e .
```

If editable install fails on an older `pip`, use `pip install .` and run from the project root with `PYTHONPATH=.` set, or upgrade pip as above.

Copy `.env.example` to `.env` and fill values.

## Google Service Account and Sheet

1. Create a project in Google Cloud Console, enable **Google Sheets API**.
2. Create a **Service Account**, create a JSON key.
3. Create or pick a Google Sheet; copy its ID from the URL (`/d/<ID>/`).
4. **Share the Sheet** with the service account email (e.g. `something@project.iam.gserviceaccount.com`) as **Editor**.
5. Set either `GOOGLE_SERVICE_ACCOUNT_JSON` (full JSON as one line) or `GOOGLE_SERVICE_ACCOUNT_KEY_PATH` to the key file path.

## Run locally

```bash
python -m src.run
```

Dry run (no Sheets, no email):

```bash
python -m src.run --dry-run
```

## Environment variables

| Variable | Required (normal run) | Description |
|----------|-------------------------|-------------|
| `GOOGLE_SHEETS_ID` | yes | Spreadsheet ID from the URL |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | one of JSON/path | Service account key JSON as a single-line string |
| `GOOGLE_SERVICE_ACCOUNT_KEY_PATH` | one of JSON/path | Path to the JSON key file (local/Docker volume) |
| `GOOGLE_SHEET_TAB` | no | Log worksheet name (default `log`) |
| `SHEET_LAYOUT` | no | `log` (default) or `daily` (one tab per `YYYY-MM-DD`) |
| `EMAIL_SMTP_HOST` / `PORT` / `USER` / `PASS` | yes | SMTP settings |
| `EMAIL_FROM` / `EMAIL_TO` | yes | Envelope addresses |
| `TRADINGVIEW_SCREENERS` | no | Optional JSON for future dynamic screeners |
| `LOG_LEVEL` | no | e.g. `INFO`, `DEBUG` |
| `DRY_RUN` | no | `1` / `true` skips Sheets and email (like `--dry-run`) |

Full list with placeholders: [.env.example](.env.example).

## Railway

1. Create a **new project** and deploy using the repo root (Dockerfile builds the app and runs `python -m src.run`).
2. In **Variables**, add every secret from `.env.example` (for `GOOGLE_SERVICE_ACCOUNT_JSON`, paste the full JSON; Railway stores it as one variable).
3. Add a **Cron** service or scheduled job (per Railway’s current UI): same image, schedule e.g. daily, start command **`python -m src.run`** (already the Dockerfile `CMD`; override only if you use a different entry).
4. Optional: set `DRY_RUN=1` once to verify the container starts without touching Sheets or SMTP.

## Troubleshooting

- **403 on Sheets**: Share the spreadsheet with the service account email as Editor; wait a minute and retry.
- **Wrong or empty scanner results**: Edit filters in `src/screeners.py`. Lower `.limit()` if you suspect throttling; see [TradingView-Screener fields](https://shner-elmo.github.io/TradingView-Screener/fields/stocks.html).
- **SMTP / Gmail**: Use an [App Password](https://support.google.com/accounts/answer/185833) (not your normal password), `smtp.gmail.com`, port `587`. For port `465`, the code uses implicit TLS (`SMTP_SSL`).
- **Idempotency**: With `SHEET_LAYOUT=log`, a second run on the same calendar day **removes existing rows for that `run_date`** in the log tab, then appends the new result set. With `daily`, the tab for that date is **cleared and rewritten**.

## Customize screeners

Edit `src/screeners.py` (the `Query` inside each function) and the **`SCREENER_REGISTRY`** list in `src/run.py`. Field names: [TradingView-Screener fields](https://shner-elmo.github.io/TradingView-Screener/fields/stocks.html).
