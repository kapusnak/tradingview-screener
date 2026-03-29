"""Entry point: run all screeners, log to Sheets, send email."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from datetime import date
from typing import Optional

import pandas as pd

from src import email_client, screeners, sheet_client
from src.config import dry_run_from_environment, load_settings

logger = logging.getLogger(__name__)

# Register screener callables here (name comes from each function's return or _run_query).
ScreenerFn = Callable[[], tuple[str, pd.DataFrame]]

SCREENER_REGISTRY: list[ScreenerFn] = [
    screeners.run_big_volume_screener,
    screeners.run_ten_percent_up_screener,
    screeners.run_weekly_20pct_gainers_screener,
    screeners.run_pullback_strong_trend_screener,
]


def build_combined_dataframe(run_date: str, results: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    """Concatenate screener frames, add run_date, normalize ticker→symbol, order columns."""
    pieces: list[pd.DataFrame] = []
    for screener_name, df in results:
        if df.empty:
            part = df.copy()
        else:
            part = df.copy()
        part["screener_name"] = screener_name
        if "ticker" in part.columns and "symbol" not in part.columns:
            part = part.rename(columns={"ticker": "symbol"})
        pieces.append(part)

    if not pieces:
        return pd.DataFrame()

    non_empty = [p for p in pieces if not p.empty]
    if not non_empty:
        return pd.DataFrame()

    out = pd.concat(non_empty, ignore_index=True)
    out.insert(0, "run_date", run_date)

    preferred = [
        "run_date",
        "screener_name",
        "symbol",
        *screeners.STANDARD_SCANNER_OUTPUT_FIELDS,
    ]
    rest = [c for c in out.columns if c not in preferred]
    ordered = [c for c in preferred if c in out.columns] + rest
    return out[ordered]


def _print_dry_run_summary(run_date: str, results: list[tuple[str, pd.DataFrame]]) -> None:
    """Readable stdout summary (one block per screener)."""
    width = 72
    line = "=" * width
    print()
    print(line)
    print(f"  DRY RUN SUMMARY    run_date={run_date}")
    print(line)

    total_rows = 0
    for screener_name, df in results:
        n = len(df)
        total_rows += n
        print(f"\n  {screener_name}    {n} row(s)")
        print("  " + "-" * (width - 4))
        if df.empty:
            print("  (no matches)")
            continue
        sym = "symbol" if "symbol" in df.columns else "ticker"
        want = [sym, *screeners.STANDARD_SCANNER_OUTPUT_FIELDS]
        show = [c for c in want if c in df.columns]
        tbl = df[show].to_string(index=False, max_rows=20)
        for tbl_line in tbl.splitlines():
            print(f"  {tbl_line}")

    print()
    print("  " + "-" * (width - 4))
    print(f"  Total rows (all screeners): {total_rows}")
    print(line)
    print()


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="TradingView screeners → Google Sheets → email")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch screeners only; skip Google Sheets and email",
    )
    args = parser.parse_args(argv)

    dry_run = bool(args.dry_run or dry_run_from_environment())
    settings = load_settings(for_real_run=not dry_run)
    _configure_logging(settings.log_level)

    if settings.tradingview_screeners_json is not None:
        logger.debug(
            "TRADINGVIEW_SCREENERS is set (not used by built-in screeners yet): %s",
            type(settings.tradingview_screeners_json).__name__,
        )

    run_date = date.today().isoformat()
    logger.info("Starting run for run_date=%s dry_run=%s", run_date, dry_run)

    try:
        results: list[tuple[str, pd.DataFrame]] = []
        for fn in SCREENER_REGISTRY:
            name, df = fn()
            results.append((name, df))

        combined = build_combined_dataframe(run_date, results)
        logger.info("Combined rows: %s", len(combined))

        if dry_run:
            _print_dry_run_summary(run_date, results)
            return 0

        sheet_client.write_dataframe(settings, combined, run_date)
        email_client.send_screener_summary_html(
            run_date=run_date,
            sheet_id=settings.google_sheets_id,
            df=combined,
            smtp_settings=settings.smtp,
        )
    except Exception:
        logger.exception("Run failed")
        return 1

    logger.info("Run finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
