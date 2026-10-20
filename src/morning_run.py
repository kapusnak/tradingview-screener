"""Weekday morning job: StockCharts $NASI + $VIX PNGs → Telegram.

Separate from the evening TradingView scanner (``python -m src.run``). Sends only
two PNG documents, nothing else. Schedule: Monday–Friday 08:15 Europe/Prague
(DST-safe via two UTC crons + a local-time guard). Weekends are a no-op.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from src.config import dry_run_from_environment, load_morning_settings
from src.stockcharts import CHARTS, fetch_all_charts, png_dimensions
from src.telegram_client import TelegramDocument, send_chart_documents

logger = logging.getLogger(__name__)

PRAGUE_TZ = ZoneInfo("Europe/Prague")
# 08:00–08:59 Prague: covers 08:15 plus typical scheduler delay.
TARGET_HOUR = 8


def _env_flag(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def should_send_morning_charts(now: datetime, *, force: bool = False) -> tuple[bool, str]:
    """
    Whether this run should send charts.

    UTC cron fires twice on weekdays (06:15 and 07:15 UTC) so 08:15 Prague is hit
    in both CET and CEST. This guard:
    - skips Saturday and Sunday in Europe/Prague entirely
    - skips the DST slot that is not 08:xx Prague
    ``force`` is for manual ``workflow_dispatch`` / local tests only.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(PRAGUE_TZ)
    stamp = local.strftime("%A %Y-%m-%d %H:%M %Z")
    if force:
        return True, f"forced send ({stamp})"
    if local.weekday() >= 5:
        return False, f"weekend in Europe/Prague ({stamp}); no morning charts"
    if local.hour != TARGET_HOUR:
        return False, (
            f"outside 08:00–08:59 Europe/Prague ({stamp}); other DST cron slot"
        )
    return True, f"weekday morning window ({stamp})"


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
        description="Send $NASI and $VIX StockCharts PNGs to Telegram (weekday mornings)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate PNGs only; skip Telegram",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the Mon–Fri 08:15 Europe/Prague window (manual tests)",
    )
    args = parser.parse_args(argv)

    dry_run = bool(args.dry_run or dry_run_from_environment())
    force = bool(args.force or _env_flag("MORNING_FORCE"))
    _configure_logging("INFO")

    now = datetime.now(timezone.utc)
    send, reason = should_send_morning_charts(now, force=force)
    if not send:
        logger.info("Morning charts skipped: %s", reason)
        return 0

    settings = load_morning_settings(for_real_run=not dry_run)
    _configure_logging(settings.log_level)
    logger.info("Morning charts starting: %s dry_run=%s", reason, dry_run)

    try:
        fetched = fetch_all_charts(CHARTS)
        documents: list[TelegramDocument] = []
        for spec, data in fetched:
            width, height = png_dimensions(data)
            logger.info(
                "Ready %s: %sx%s px, %s bytes, caption=%s",
                spec.filename,
                width,
                height,
                len(data),
                spec.caption,
            )
            documents.append(
                TelegramDocument(filename=spec.filename, data=data, caption=spec.caption)
            )

        if dry_run:
            logger.info("Dry run: not sending %s PNG document(s) to Telegram", len(documents))
            return 0

        assert settings.telegram is not None
        send_chart_documents(telegram=settings.telegram, documents=documents)
    except Exception:
        logger.exception("Morning charts run failed")
        return 1

    logger.info("Morning charts finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
