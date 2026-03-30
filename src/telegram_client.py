"""Send screener summaries via Telegram Bot API (no extra dependencies)."""

from __future__ import annotations

import html
import json
import logging
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, List

import pandas as pd

if TYPE_CHECKING:
    from src.config import TelegramSettings

logger = logging.getLogger(__name__)

# Telegram hard limit is 4096; stay under for encoding/safety.
_MAX_MESSAGE_CHARS = 4000

# Internal screener keys (from ``screeners._run_query``) → user-facing titles.
SCREENER_DISPLAY_NAMES: dict[str, str] = {
    "big_volume": "Big Volume",
    "10pct_up": "10% Up",
    "weekly_20pct_gainers": "Weekly 20% Gainers",
    "pullback_strong_trend": "Pullback in Strong Trend",
}


def screener_display_name(internal_key: str) -> str:
    if internal_key in SCREENER_DISPLAY_NAMES:
        return SCREENER_DISPLAY_NAMES[internal_key]
    return internal_key.replace("_", " ").title()


def _symbol_only(raw: object) -> str:
    s = str(raw).strip()
    if ":" in s:
        return s.rsplit(":", 1)[-1]
    return s


def _fmt_pct(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{float(value):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_rel_vol(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "—"


def _pre_table_lines(df: pd.DataFrame, sym_col: str) -> list[str]:
    """Monospace table: Ticker | Chg % | Rel vol (one data row per line)."""
    w_sym, w_chg, w_rel = 10, 10, 8
    header = f"{'Ticker':<{w_sym}}{'Chg %':>{w_chg}}{'Rel vol':>{w_rel}}"
    sep = "-" * len(header)
    out = [header, sep]
    for _, row in df.iterrows():
        sym = _symbol_only(row.get(sym_col, ""))
        if len(sym) > w_sym:
            sym = sym[: w_sym - 1] + "…"
        chg = _fmt_pct(row.get("change"))
        relv = _fmt_rel_vol(row.get("relative_volume"))
        out.append(f"{sym:<{w_sym}}{chg:>{w_chg}}{relv:>{w_rel}}")
    return out


def format_results_telegram_html(run_date: str, results: list[tuple[str, pd.DataFrame]]) -> str:
    """Compact HTML: bold section titles, monospace tables, no extra columns."""
    lines: list[str] = [
        f"<b>TradingView screeners</b> — {html.escape(run_date)}",
        "",
    ]
    total = 0
    for internal_name, df in results:
        total += len(df)
        title = html.escape(screener_display_name(internal_name))
        lines.append(f"<b>{title}</b>")
        if df.empty:
            lines.append("<i>No matches</i>")
        else:
            sym_col = "symbol" if "symbol" in df.columns else "ticker"
            pre_body = "\n".join(_pre_table_lines(df, sym_col))
            lines.append(f"<pre>{html.escape(pre_body)}</pre>")
        lines.append("")

    lines.append(f"<i>Total: {total} symbols</i>")
    return "\n".join(lines)


def _split_html_message(text: str, max_len: int = _MAX_MESSAGE_CHARS) -> List[str]:
    if len(text) <= max_len:
        return [text]
    # Prefer splitting on blank lines (between screener sections).
    parts = text.split("\n\n")
    chunks: list[str] = []
    buf = ""
    for p in parts:
        candidate = p if not buf else buf + "\n\n" + p
        if len(candidate) <= max_len:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            if len(p) <= max_len:
                buf = p
            else:
                # Single huge section: hard-split by lines
                sub = p
                while sub:
                    chunks.append(sub[:max_len])
                    sub = sub[max_len:].lstrip("\n")
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def send_screener_summary(
    *,
    telegram: "TelegramSettings",
    run_date: str,
    results: list[tuple[str, pd.DataFrame]],
) -> None:
    """POST sendMessage for each chunk (Telegram length limit)."""
    body = format_results_telegram_html(run_date, results)
    chunks = _split_html_message(body)
    url = f"https://api.telegram.org/bot{telegram.bot_token}/sendMessage"
    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": telegram.chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
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
