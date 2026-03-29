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
import pandas as pd
from tradingview_screener import Query, col

logger = logging.getLogger(__name__)

# ``change`` in the scanner = **percent** move for that timeframe (10 → 10%).
# ``change_abs`` = absolute price change in the quote currency (e.g. USD).

# Default row cap per query; increase carefully (TradingView may throttle).
_DEFAULT_LIMIT = 150

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

# Universe: all US stocks in ``america`` that pass the filters below (plus sector list).
# Optional: restrict to explicit symbols with ``Query().set_tickers("NASDAQ:AAPL", ...)``.

# Relative Volume in UI: timeframe “1 day”, Above, 2.5 → scanner field ``relative_volume``
# (daily rel vol). Do not use ``relative_volume_10d_calc`` for that — it is a different
# metric (10‑session calc). Override only if you intentionally want another field.
BIG_VOLUME_REL_VOLUME_FIELD: str = "relative_volume"


def _run_query(screener_name: str, query: Query) -> tuple[str, pd.DataFrame]:
    """Execute a built Query and return (name, DataFrame)."""
    total, df = query.get_scanner_data()
    logger.info("Screener %s: API reports total=%s, rows_in_page=%s", screener_name, total, len(df))
    return screener_name, df.copy()


def run_big_volume_screener() -> tuple[str, pd.DataFrame]:
    """
    Mirrors the saved TradingView screener **"Big Volume"** (your screenshots).

    UI rules → API fields:
      - US → ``america`` (full US scanner universe, not a watchlist)
      - Price > 5 USD → ``close``
      - Change > 0% → ``change`` (**percent**, not dollars; see module note)
      - Revenue, Quarterly QoQ > 15% → ``total_revenue_qoq_growth_fq``
      - “Price × Average Volume 30 days” > 100M USD → ``AvgValue.Traded_30d``
        (TradingView’s 30D average **dollar** value traded; closest scanner field to
        that tooltip)
      - Market cap > 300M USD → ``market_cap_basic``
      - Rel Volume, **1 day**, > 2.5 → ``relative_volume`` (``BIG_VOLUME_REL_VOLUME_FIELD``)
      - “Volume Change % 1 day” > 30% → ``volume_change`` (1D)

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
        col("total_revenue_qoq_growth_fq") > 15,
        col("AvgValue.Traded_30d") > 100_000_000,
        col(rel_field) > 2.5,
        col("volume_change") > 30,
    ]
    if BIG_VOLUME_SECTORS:
        filters.append(col("sector").isin(list(BIG_VOLUME_SECTORS)))

    q = (
        Query()
        .set_markets("america")
        .select(
            "name",
            "close",
            "change",
            "volume",
            "volume_change",
            "relative_volume",
            "relative_volume_10d_calc",
            "market_cap_basic",
            "total_revenue_qoq_growth_fq",
            "AvgValue.Traded_30d",
            "sector",
        )
        .where(*filters)
        .order_by("volume", ascending=False)
        .limit(_DEFAULT_LIMIT)
    )
    return _run_query("big_volume", q)


def run_ten_percent_up_screener() -> tuple[str, pd.DataFrame]:
    """
    **"10% Up"** (your UI): US, no sector filter, no watchlist.

    UI → API:
      - Price > 5 USD → ``close``
      - Change > 10% → ``change`` > 10 (**percent**; not ``change_abs``)
      - Revenue Quarterly QoQ > 15% → ``total_revenue_qoq_growth_fq``
      - Market cap > 300M USD → ``market_cap_basic``
      - Rel Volume > 1.5 (1 day) → ``relative_volume``
      - EMA(10) > EMA(20) → ``EMA10`` greater than ``EMA20`` (daily; ``col()`` comparison)
      - Price × Vol > 50M USD → ``Value.Traded`` (session / 1D dollar volume)

    Strict AND may return zero rows on some days; thresholds are easy to relax below.
    """
    filters = [
        col("close") > 5,
        col("change") > 10,
        col("total_revenue_qoq_growth_fq") > 15,
        col("market_cap_basic") > 300_000_000,
        col("relative_volume") > 1.5,
        col("EMA10") > col("EMA20"),
        col("Value.Traded") > 50_000_000,
    ]
    q = (
        Query()
        .set_markets("america")
        .select(
            "name",
            "close",
            "change",
            "volume",
            "relative_volume",
            "market_cap_basic",
            "total_revenue_qoq_growth_fq",
            "EMA10",
            "EMA20",
            "Value.Traded",
        )
        .where(*filters)
        .order_by("change", ascending=False)
        .limit(_DEFAULT_LIMIT)
    )
    return _run_query("10pct_up", q)
