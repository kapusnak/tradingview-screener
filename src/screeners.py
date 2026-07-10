"""
TradingView scanner queries defined in code (not loaded from your TradingView account).

The TradingView *website* lets you save screeners under your login, but this project does
not use those URLs or your username. It calls TradingView's scanner HTTP API via the
`tradingview-screener` library: each function below builds a Query (markets, filters,
columns) in Python.

To add another screener, copy a function below, map UI rules to fields from the
library's field list, and register it in ``src/run.py``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
from tradingview_screener import Query, col

logger = logging.getLogger(__name__)

# ``change`` in the scanner = **percent** move for that timeframe (10 → 10%).
# ``change_abs`` = absolute price change in the quote currency (e.g. USD).

# Default row cap per query; increase carefully (TradingView may throttle).
_DEFAULT_LIMIT = 150

# TradingView UI **Market → USA**: use ``set_markets("america")`` only. Do **not** filter
# ``country == "United States"``: the UI means US-listed names; the API’s ``country`` is
# issuer domicile, so a strict US filter drops symbols the UI still shows (e.g. some ADRs).

# Same output shape for every screener (TradingView column order; ``ticker`` is always
# first from the API, then renamed to ``symbol`` in ``run.py``). ``name`` is included
# for readability. Last column is **Industry** (scanner field ``industry``).
STANDARD_SCANNER_OUTPUT_FIELDS: tuple[str, ...] = (
    "name",
    "change",
    "relative_volume",
    "Value.Traded",
    "AvgValue.Traded_60d",
    "market_cap_basic",
    "total_revenue_qoq_growth_fq",
    "total_revenue_yoy_growth_fq",
    "industry",
)

# --- "Big Volume" screener (TradingView UI) ---------------------------------
# Eleven sectors checked in your UI (scanner API uses Title Case on each word).
BIG_VOLUME_SECTORS: tuple[str, ...] = (
    "Commercial Services",
    "Communications",
    "Consumer Services",
    "Electronic Technology",
    "Energy Minerals",
    "Finance",
    "Health Services",
    "Health Technology",
    "Industrial Services",
    "Technology Services",
    "Transportation",
)

# Universe: ``america`` market symbols that pass the filters below (plus sector list).
# Optional: restrict to explicit symbols with ``Query().set_tickers("NASDAQ:AAPL", ...)``.

# Relative Volume in UI: timeframe “1 day”, Above, 2.5 → scanner field ``relative_volume``
# (daily rel vol). Do not use ``relative_volume_10d_calc`` for that — it is a different
# metric (10‑session calc). Override only if you intentionally want another field.
BIG_VOLUME_REL_VOLUME_FIELD: str = "relative_volume"

# UI table is sorted by **Rel Volume** (desc). Sorting by raw ``volume`` (shares) surfaces
# mega‑caps first and can push high‑rel‑vol names like CHYM past ``limit`` even though they match.
BIG_VOLUME_RESULT_LIMIT: int = 500

# --- "Weekly Gainer" (Friday only) --------------------------------------------
# Market-cap floor (USD): > 300M, same as your TradingView rule.
WEEKLY_20PCT_MIN_MARKET_CAP_USD: float = 300_000_000
# Price × avg vol 30D floor (USD): > 50M.
WEEKLY_MIN_AVG_VALUE_TRADED_30D_USD: float = 50_000_000
# 1-week performance floor (percent): > 30%.
WEEKLY_MIN_PERF_W_PCT: float = 30
# Calendar for weekday gating (Telegram) and weekly screener (Friday only), Europe/Prague.
WEEKLY_20PCT_CALENDAR_TZ = ZoneInfo("Europe/Prague")
# Include weekly performance in API output (Telegram shows ``Perf.W`` as "W Chg %").
WEEKLY_20PCT_OUTPUT_FIELDS: tuple[str, ...] = STANDARD_SCANNER_OUTPUT_FIELDS + ("Perf.W",)


def _prague_calendar_date() -> date:
    return datetime.now(WEEKLY_20PCT_CALENDAR_TZ).date()


def is_weekday_in_prague() -> bool:
    """True Monday–Friday in ``WEEKLY_20PCT_CALENDAR_TZ`` (Prague)."""
    return _prague_calendar_date().weekday() < 5


def _is_weekly_20pct_screener_active_day() -> bool:
    """True on Friday in ``WEEKLY_20PCT_CALENDAR_TZ`` (Prague)."""
    return _prague_calendar_date().weekday() == 4


def include_screener_in_text_summary(internal_name: str, df: pd.DataFrame) -> bool:
    """
    Whether Telegram / dry-run should show this screener at all (title + body).

    Weekly Gainer is hidden Mon–Thu Prague when it did not run (empty). On Friday
    it is always shown, including an empty \"No matches\" block after a real query.
    """
    if internal_name != "weekly_20pct_gainers":
        return True
    return _is_weekly_20pct_screener_active_day() or not df.empty


def _run_query(screener_name: str, query: Query) -> tuple[str, pd.DataFrame]:
    """Execute a built Query and return (name, DataFrame)."""
    total, df = query.get_scanner_data()
    logger.info("Screener %s: API reports total=%s, rows_in_page=%s", screener_name, total, len(df))
    return screener_name, df.copy()


def run_big_volume_screener() -> tuple[str, pd.DataFrame]:
    """
    Mirrors the saved TradingView screener **"Big Volume"** (your screenshots).

    UI rules → API fields:
      - Market USA → ``america`` only (``set_markets("america")``; no ``country`` filter)
      - Price > 5 USD → ``close``
      - Change > 0% → ``change`` (**percent**, not dollars; see module note)
      - Revenue, Quarterly YoY > 15% → ``total_revenue_yoy_growth_fq``
      - “Price × Average Volume 30 days” > 100M USD → ``AvgValue.Traded_30d``
        (TradingView’s 30D average **dollar** value traded; closest scanner field to
        that tooltip)
      - Market cap > 300M USD → ``market_cap_basic``
      - Rel Volume, **1 day**, > 2.5 → ``relative_volume`` (``BIG_VOLUME_REL_VOLUME_FIELD``)
      - “Volume Change % 1 day” > 30% → ``volume_change`` (1D)

    **Sort / cap:** same as typical UI view — order by ``relative_volume`` descending (not share
    ``volume``), with ``BIG_VOLUME_RESULT_LIMIT`` rows so matches are not truncated early.

    **Sectors:** the 11 checked sectors in your UI are in ``BIG_VOLUME_SECTORS``
    (Title Case as returned by the API).

    **Zero rows:** strict AND filters may return nobody on some days; ease thresholds
    on *other* filters — keep ``relative_volume`` for 1D rel vol as in the UI.
    """
    rel_field = BIG_VOLUME_REL_VOLUME_FIELD
    filters = [
        col("close") > 5,
        col("change") > 0,
        col("market_cap_basic") > 300_000_000,
        col("total_revenue_yoy_growth_fq") > 15,
        col("AvgValue.Traded_30d") > 100_000_000,
        col(rel_field) > 2.5,
        col("volume_change") > 30,
    ]
    if BIG_VOLUME_SECTORS:
        filters.append(col("sector").isin(list(BIG_VOLUME_SECTORS)))

    q = (
        Query()
        .set_markets("america")
        .select(*STANDARD_SCANNER_OUTPUT_FIELDS)
        .where(*filters)
        .order_by(rel_field, ascending=False)
        .limit(BIG_VOLUME_RESULT_LIMIT)
    )
    return _run_query("big_volume", q)


def run_ten_percent_up_screener() -> tuple[str, pd.DataFrame]:
    """
    **"10% Up"** (your UI): USA market, no sector filter, no watchlist.

    UI → API:
      - Market USA → ``america`` only (no ``country`` filter)
      - Price > 5 USD → ``close``
      - Change > 10% → ``change`` > 10 (**percent**; not ``change_abs``)
      - Revenue Quarterly YoY > 15% → ``total_revenue_yoy_growth_fq``
      - Market cap > 300M USD → ``market_cap_basic``
      - Rel Volume > 1.5 (1 day) → ``relative_volume``
      - EMA(10) > EMA(20) → ``EMA10`` greater than ``EMA20`` (daily; ``col()`` comparison)
      - Price × Vol > 50M USD → ``Value.Traded`` (session / 1D dollar volume)

    Strict AND may return zero rows on some days; thresholds are easy to relax below.
    """
    filters = [
        col("close") > 5,
        col("change") > 10,
        col("total_revenue_yoy_growth_fq") > 15,
        col("market_cap_basic") > 300_000_000,
        col("relative_volume") > 1.5,
        col("EMA10") > col("EMA20"),
        col("Value.Traded") > 50_000_000,
    ]
    q = (
        Query()
        .set_markets("america")
        .select(*STANDARD_SCANNER_OUTPUT_FIELDS)
        .where(*filters)
        .order_by("change", ascending=False)
        .limit(_DEFAULT_LIMIT)
    )
    return _run_query("10pct_up", q)


def run_weekly_20pct_gainers_screener() -> tuple[str, pd.DataFrame]:
    """
    **"Weekly Gainer"** — only queried on **Friday** (Europe/Prague).

    **Monday–Thursday and weekends** on that calendar return an empty DataFrame (no API call). Uses
    ``datetime.now(WEEKLY_20PCT_CALENDAR_TZ)`` so the script uses the **local date in Prague**
    (CET/CEST); you can add a **time-of-day** cutoff if you want stricter behavior.

    UI → API (weekly performance is ``Perf.W``):
      - Market USA → ``america`` only (no ``country`` filter)
      - Price > 5 USD → ``close`` > 5
      - Price × Average Volume 30 days > 50M USD → ``AvgValue.Traded_30d`` > 50M
      - Market cap > 300M USD → ``market_cap_basic`` > ``WEEKLY_20PCT_MIN_MARKET_CAP_USD`` (300M)
      - Chg % 1 week > 30% → ``Perf.W`` > 30
    """
    if not _is_weekly_20pct_screener_active_day():
        now_local = datetime.now(WEEKLY_20PCT_CALENDAR_TZ)
        logger.info(
            "Screener weekly_20pct_gainers: skipped (runs only Friday Europe/Prague); now=%s weekday=%s",
            now_local.strftime("%Y-%m-%d %H:%M %Z"),
            now_local.date().weekday(),
        )
        return "weekly_20pct_gainers", pd.DataFrame()

    mc_min = WEEKLY_20PCT_MIN_MARKET_CAP_USD
    filters = [
        col("close") > 5,
        col("AvgValue.Traded_30d") > WEEKLY_MIN_AVG_VALUE_TRADED_30D_USD,
        col("market_cap_basic") > mc_min,
        col("Perf.W") > WEEKLY_MIN_PERF_W_PCT,
    ]
    q = (
        Query()
        .set_markets("america")
        .select(*WEEKLY_20PCT_OUTPUT_FIELDS)
        .where(*filters)
        .order_by("Perf.W", ascending=False)
        .limit(_DEFAULT_LIMIT)
    )
    return _run_query("weekly_20pct_gainers", q)


def run_strong_fresh_names_screener() -> tuple[str, pd.DataFrame]:
    """
    **"Strong Fresh Names"** (from your screenshot): US-listed names with recent IPOs,
    strong quarterly growth, price above short/medium trend filters, and high daily liquidity.

    UI → API:
      - Market USA → ``america`` only (no ``country`` filter)
      - Chg from open > 0% → ``change_from_open`` > 0
      - IPO offer date Past 3 years → ``ipo_offer_date`` (Unix seconds) within the last 3 years
      - Price > 10 USD → ``close`` > 10
      - Market cap > 2B USD → ``market_cap_basic`` > 2_000_000_000
      - Revenue growth, Quarterly YoY > 19% → ``total_revenue_yoy_growth_fq`` > 19
      - SMA(50) < Price → ``SMA50`` < ``close``
      - SMA(20) < Price → ``SMA20`` < ``close``
      - SMA(20) > SMA(50) → ``SMA20`` > ``SMA50``
      - EMA(10) < Price → ``EMA10`` < ``close``
      - Avg vol, 10D > 500K → ``average_volume_10d_calc`` > 500_000

    Sort like the screenshot request: ``relative_volume`` descending for the current day.
    """
    three_years_ago_ts = int(
        (pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.DateOffset(years=3)).timestamp()
    )
    filters = [
        col("change_from_open") > 0,
        col("ipo_offer_date") >= three_years_ago_ts,
        col("close") > 10,
        col("market_cap_basic") > 2_000_000_000,
        col("total_revenue_yoy_growth_fq") > 19,
        col("SMA50") < col("close"),
        col("SMA20") < col("close"),
        col("SMA20") > col("SMA50"),
        col("EMA10") < col("close"),
        col("average_volume_10d_calc") > 500_000,
    ]
    q = (
        Query()
        .set_markets("america")
        .select(*STANDARD_SCANNER_OUTPUT_FIELDS)
        .where(*filters)
        .order_by("relative_volume", ascending=False)
        .limit(_DEFAULT_LIMIT)
    )
    return _run_query("strong_fresh_names", q)
