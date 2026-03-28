# Implementation plan (summary)

## Files

- `pyproject.toml` — dependencies and packaging (`src` package).
- `src/config.py` — environment variables and settings.
- `src/screeners.py` — TradingView `Query` wrappers per screener.
- `src/sheet_client.py` — gspread: log tab or daily worksheet, idempotent write.
- `src/email_client.py` — HTML summary via SMTP.
- `src/run.py` — entrypoint: fetch → DataFrame → Sheets → email.
- `Dockerfile` — Railway/cron: `python -m src.run`.
- `.env.example` — documented variables.

## Dependencies

- `tradingview-screener`, `pandas`, `gspread`, `google-auth`, `python-dotenv`.

## Data flow

1. **Screeners** — Each function runs a `Query`, returns `(screener_name, DataFrame)`.
2. **Aggregate** — `run.py` adds `screener_name` and `run_date`, renames `ticker` → `symbol`, `pd.concat`.
3. **Sheets** — **Pattern A (default):** worksheet `log`; delete rows whose `run_date` matches today, append new rows (idempotent per day). **Pattern B:** worksheet named `YYYY-MM-DD`; clear and rewrite.
4. **Email** — HTML grouped by `screener_name` with sheet link.
