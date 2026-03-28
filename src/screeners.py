"""TradingView scanner queries — one function per saved screener."""

from __future__ import annotations

import logging
import pandas as pd
from tradingview_screener import Query, col

logger = logging.getLogger(__name__)

# Default row cap per query; increase carefully (TradingView may throttle).
_DEFAULT_LIMIT = 150


def _run_query(screener_name: str, query: Query) -> tuple[str, pd.DataFrame]:
    """Execute a built Query and return (name, DataFrame)."""
    total, df = query.get_scanner_data()
    logger.info("Screener %s: API reports total=%s, rows_in_page=%s", screener_name, total, len(df))
    return screener_name, df.copy()


def run_us_momentum_screener() -> tuple[str, pd.DataFrame]:
    """
    US stocks: positive day change, minimum liquidity, sorted by relative volume.
    Tune filters in Query below for your definition of momentum.
    """
    q = (
        Query()
        .set_markets("america")
        .select(
            "name",
            "close",
            "volume",
            "market_cap_basic",
            "change",
            "relative_volume_10d_calc",
        )
        .where(
            col("change") > 0,
            col("volume") > 500_000,
        )
        .order_by("relative_volume_10d_calc", ascending=False)
        .limit(_DEFAULT_LIMIT)
    )
    return _run_query("us_momentum", q)


def run_us_largecap_volume_screener() -> tuple[str, pd.DataFrame]:
    """US large caps by dollar volume (illustrative floor on market cap)."""
    q = (
        Query()
        .set_markets("america")
        .select(
            "name",
            "close",
            "volume",
            "market_cap_basic",
            "change",
            "relative_volume_10d_calc",
        )
        .where(col("market_cap_basic") >= 10_000_000_000)  # ~$10B+
        .order_by("volume", ascending=False)
        .limit(_DEFAULT_LIMIT)
    )
    return _run_query("us_largecap_volume", q)


def run_us_high_relative_volume_screener() -> tuple[str, pd.DataFrame]:
    """US names trading above recent volume (relative volume > 1.5)."""
    q = (
        Query()
        .set_markets("america")
        .select(
            "name",
            "close",
            "volume",
            "market_cap_basic",
            "change",
            "relative_volume_10d_calc",
        )
        .where(
            col("relative_volume_10d_calc") > 1.5,
            col("volume") > 250_000,
        )
        .order_by("relative_volume_10d_calc", ascending=False)
        .limit(_DEFAULT_LIMIT)
    )
    return _run_query("us_high_relative_volume", q)
