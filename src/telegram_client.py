"""Send screener summaries and chart documents via Telegram Bot API (no extra dependencies)."""

from __future__ import annotations

import html
import json
import logging
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Sequence

import pandas as pd

from src import screeners

if TYPE_CHECKING:
    from src.config import TelegramSettings

logger = logging.getLogger(__name__)

# Telegram hard limit is 4096; stay under for encoding/safety.
_MAX_MESSAGE_CHARS = 4000

# Internal screener keys (from ``screeners._run_query``) → user-facing titles.
SCREENER_DISPLAY_NAMES: dict[str, str] = {
    "big_volume": "Big Volume",
    "10pct_up": "10% Up",
    "weekly_20pct_gainers": "Weekly Gainer",
    "strong_fresh_names": "Strong Fresh Names",
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


# Per-screener change column: (scanner field, Telegram header).
_SCREENER_CHG_COLUMN: dict[str, tuple[str, str]] = {
    "weekly_20pct_gainers": ("Perf.W", "W Chg %"),
}


def _chg_column_for_screener(internal_name: str) -> tuple[str, str]:
    return _SCREENER_CHG_COLUMN.get(internal_name, ("change", "Chg %"))


def _pre_table_lines(df: pd.DataFrame, sym_col: str, *, internal_name: str) -> list[str]:
    """Monospace table: Ticker | Chg % (or W Chg %) | Rel vol (one data row per line)."""
    chg_field, chg_header = _chg_column_for_screener(internal_name)
    w_sym, w_chg, w_rel = 10, max(10, len(chg_header)), 8
    header = f"{'Ticker':<{w_sym}}{chg_header:>{w_chg}}{'Rel vol':>{w_rel}}"
    sep = "-" * len(header)
    out = [header, sep]
    for _, row in df.iterrows():
        sym = _symbol_only(row.get(sym_col, ""))
        if len(sym) > w_sym:
            sym = sym[: w_sym - 1] + "…"
        chg = _fmt_pct(row.get(chg_field))
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
        if not screeners.include_screener_in_text_summary(internal_name, df):
            continue
        total += len(df)
        title = html.escape(screener_display_name(internal_name))
        lines.append(f"<b>{title} ({len(df)})</b>")
        if df.empty:
            lines.append("<i>No matches</i>")
        else:
            sym_col = "symbol" if "symbol" in df.columns else "ticker"
            pre_body = "\n".join(_pre_table_lines(df, sym_col, internal_name=internal_name))
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


@dataclass(frozen=True)
class TelegramDocument:
    """PNG (or other file) sent via sendDocument so Telegram does not recompress it."""

    filename: str
    data: bytes
    caption: str


def _multipart_body(
    fields: dict[str, str],
    files: Sequence[tuple[str, str, bytes, str]],
) -> tuple[bytes, str]:
    """Encode ``multipart/form-data``. ``files`` is (field, filename, bytes, content_type)."""
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    for field_name, filename, data, content_type in files:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _post_telegram_form(
    *,
    bot_token: str,
    method: str,
    fields: dict[str, str],
    files: Sequence[tuple[str, str, bytes, str]],
    timeout: int = 90,
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    body, content_type = _multipart_body(fields, files)
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        logger.error("Telegram API HTTP %s on %s: %s", e.code, method, err_body)
        raise


def send_document(
    *,
    telegram: "TelegramSettings",
    document: TelegramDocument,
) -> None:
    """POST sendDocument with an uploaded PNG (original pixels, no JPEG recompress)."""
    _post_telegram_form(
        bot_token=telegram.bot_token,
        method="sendDocument",
        fields={
            "chat_id": telegram.chat_id,
            "caption": document.caption,
        },
        files=[("document", document.filename, document.data, "image/png")],
    )
    logger.info("Telegram document sent (%s, %s bytes)", document.filename, len(document.data))


def send_document_media_group(
    *,
    telegram: "TelegramSettings",
    documents: Sequence[TelegramDocument],
) -> None:
    """POST sendMediaGroup of documents so the charts arrive together, uncompressed."""
    if len(documents) < 2:
        raise ValueError("sendMediaGroup needs at least two documents")
    files: list[tuple[str, str, bytes, str]] = []
    media: list[dict[str, str]] = []
    for i, document in enumerate(documents):
        attach = f"chart{i}"
        files.append((attach, document.filename, document.data, "image/png"))
        media.append(
            {
                "type": "document",
                "media": f"attach://{attach}",
                "caption": document.caption,
            }
        )
    _post_telegram_form(
        bot_token=telegram.bot_token,
        method="sendMediaGroup",
        fields={
            "chat_id": telegram.chat_id,
            "media": json.dumps(media),
        },
        files=files,
    )
    logger.info("Telegram document media group sent (%s files)", len(documents))


def send_chart_documents(
    *,
    telegram: "TelegramSettings",
    documents: Sequence[TelegramDocument],
) -> None:
    """Send chart PNGs only (no extra text, no sendPhoto). Album first; sendDocument fallback."""
    if not documents:
        raise ValueError("no documents to send")
    if len(documents) == 1:
        send_document(telegram=telegram, document=documents[0])
        return
    try:
        send_document_media_group(telegram=telegram, documents=documents)
    except urllib.error.HTTPError:
        logger.warning("sendMediaGroup(document) failed; sending each chart with sendDocument")
        for document in documents:
            send_document(telegram=telegram, document=document)
