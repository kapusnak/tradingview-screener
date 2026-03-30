"""Send screener summaries via Telegram Bot API (no extra dependencies)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, List

import pandas as pd

from src import screeners

if TYPE_CHECKING:
    from src.config import TelegramSettings

logger = logging.getLogger(__name__)

# Telegram hard limit is 4096; stay under for encoding/safety.
_MAX_MESSAGE_CHARS = 4000


def format_results_plain_text(run_date: str, results: list[tuple[str, pd.DataFrame]]) -> str:
    """Plain-text summary matching the dry-run layout (good for Telegram)."""
    lines: list[str] = [
        f"TradingView screeners — {run_date}",
        "",
    ]
    total = 0
    for screener_name, df in results:
        n = len(df)
        total += n
        lines.append(f"{screener_name} — {n} row(s)")
        lines.append("-" * 40)
        if df.empty:
            lines.append("(no matches)")
            lines.append("")
            continue
        sym = "symbol" if "symbol" in df.columns else "ticker"
        cols = [c for c in [sym, *screeners.STANDARD_SCANNER_OUTPUT_FIELDS] if c in df.columns]
        tbl = df[cols].to_string(index=False, max_rows=50)
        lines.append(tbl)
        lines.append("")
    lines.append("-" * 40)
    lines.append(f"Total rows: {total}")
    return "\n".join(lines)


def _split_message(text: str, max_len: int = _MAX_MESSAGE_CHARS) -> List[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_len:
            chunks.append(rest)
            break
        cut = rest.rfind("\n", 0, max_len)
        if cut < max_len // 2:
            cut = max_len
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return chunks


def send_screener_summary(
    *,
    telegram: "TelegramSettings",
    run_date: str,
    results: list[tuple[str, pd.DataFrame]],
) -> None:
    """POST sendMessage for each chunk (Telegram length limit)."""
    body = format_results_plain_text(run_date, results)
    chunks = _split_message(body)
    url = f"https://api.telegram.org/bot{telegram.bot_token}/sendMessage"
    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": telegram.chat_id,
            "text": chunk,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                resp.read()
            logger.info("Telegram message part %s/%s sent (%s bytes)", i + 1, len(chunks), len(chunk))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error("Telegram API HTTP %s: %s", e.code, err_body)
            raise
