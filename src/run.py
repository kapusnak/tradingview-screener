"""Entry point: run all screeners; optional Sheets, email, Telegram.

Evening Railway cron is UTC-only. Use ``30 16,17,19,20 * * 1-5`` so both
EST/EDT and regular vs 1pm early close are covered. The process sends only
in the 30-minute window starting 30 minutes before that day's NYSE close
(normally 15:30 America/New_York). Other slots no-op; full US holidays and
weekends are skipped. ``--force`` is for local tests. Always exits (Railway).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

from src import email_client, screeners, sheet_client, telegram_client
from src.config import dry_run_from_environment, load_settings

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")
# Last half-hour of the NYSE session: 15:30–16:00 ET regular, 12:30–13:00 ET early close.
PRE_CLOSE_LEAD = timedelta(minutes=30)
SEND_WINDOW = timedelta(minutes=30)
_NYSE_CALENDAR = None

# Register screener callables here (name comes from each function's return or _run_query).
ScreenerFn = Callable[[], tuple[str, pd.DataFrame]]

SCREENER_REGISTRY: list[ScreenerFn] = [
    screeners.run_big_volume_screener,
    screeners.run_ten_percent_up_screener,
    screeners.run_weekly_20pct_gainers_screener,
    screeners.run_strong_fresh_names_screener,
]


def _nyse_calendar():
    """Cached NYSE calendar (holidays + 1pm early closes)."""
    global _NYSE_CALENDAR
    if _NYSE_CALENDAR is None:
        _NYSE_CALENDAR = mcal.get_calendar("NYSE")
    return _NYSE_CALENDAR


def _env_flag(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def should_send_evening_scan(now: datetime, *, force: bool = False) -> tuple[bool, str]:
    """
    Whether this run should scan and send.

    Railway cron ``30 16,17,19,20 * * 1-5`` fires four weekday UTC times so
    15:30 ET (regular close − 30m) and 12:30 ET (1pm early close − 30m) are
    both hit in EST and EDT. This guard:
    - skips days the NYSE is shut (weekends and full holidays)
    - sends only in [close − 30m, close) so the other DST/early-close slots
      are no-ops (one send per trading day; no extra store)
    ``force`` is for local tests only.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    ny = now_utc.astimezone(NY_TZ)
    stamp = ny.strftime("%A %Y-%m-%d %H:%M %Z")
    if force:
        return True, f"forced send ({stamp})"

    session_date = ny.date()
    schedule = _nyse_calendar().schedule(start_date=session_date, end_date=session_date)
    if schedule.empty:
        return False, f"US market closed ({stamp}); holiday or weekend"

    close = schedule.iloc[0]["market_close"].to_pydatetime()
    if close.tzinfo is None:
        close = close.replace(tzinfo=timezone.utc)
    else:
        close = close.astimezone(timezone.utc)
    send_at = close - PRE_CLOSE_LEAD
    window_end = send_at + SEND_WINDOW
    send_ny = send_at.astimezone(NY_TZ).strftime("%H:%M %Z")
    close_ny = close.astimezone(NY_TZ).strftime("%H:%M %Z")
    if send_at <= now_utc < window_end:
        return True, (
            f"NYSE pre-close window ({stamp}; send {send_ny}, close {close_ny})"
        )
    return False, (
        f"outside NYSE pre-close window ({stamp}; send {send_ny}, close {close_ny}); "
        "other DST or early-close cron slot"
    )


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
        if not screeners.include_screener_in_text_summary(screener_name, df):
            continue
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
        stream=sys.stdout,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="TradingView screeners → optional Google Sheets, email, Telegram",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch screeners only; skip Sheets, email, and Telegram",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the NYSE pre-close window (manual tests)",
    )
    args = parser.parse_args(argv)

    dry_run = bool(args.dry_run or dry_run_from_environment())
    force = bool(args.force or _env_flag("EVENING_FORCE"))
    _configure_logging("INFO")

    now = datetime.now(timezone.utc)
    send, reason = should_send_evening_scan(now, force=force)
    if not send:
        logger.info("Evening scanner skipped: %s", reason)
        return 0

    settings = load_settings(for_real_run=not dry_run)
    _configure_logging(settings.log_level)

    if settings.tradingview_screeners_json is not None:
        logger.debug(
            "TRADINGVIEW_SCREENERS is set (not used by built-in screeners yet): %s",
            type(settings.tradingview_screeners_json).__name__,
        )

    run_day = date.today()
    run_date = f"{run_day.day}.{run_day.month}.{run_day.year}"
    logger.info(
        "Starting run for run_date=%s dry_run=%s (%s)",
        run_day.isoformat(),
        dry_run,
        reason,
    )

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

        if settings.sheets_enabled:
            sheet_client.write_dataframe(settings, combined, run_day)
        if settings.smtp is not None:
            email_client.send_screener_summary_html(
                run_date=run_date,
                sheet_id=settings.google_sheets_id or "",
                df=combined,
                smtp_settings=settings.smtp,
            )
        if settings.telegram is not None:
            if screeners.is_weekday_in_prague():
                telegram_client.send_screener_summary(
                    telegram=settings.telegram,
                    run_date=run_date,
                    results=results,
                )
            else:
                logger.info("Telegram skipped (weekdays only, Europe/Prague)")
    except Exception:
        logger.exception("Run failed")
        return 1

    logger.info("Run finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
