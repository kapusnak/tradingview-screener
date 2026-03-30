"""SMTP HTML summary of screener results."""

from __future__ import annotations

import html
import logging
import smtplib
from email.mime.text import MIMEText

import pandas as pd

from src.config import SmtpSettings

logger = logging.getLogger(__name__)


def _sheet_url(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}"


def build_html_summary(
    *,
    run_date: str,
    sheet_id: str,
    df: pd.DataFrame,
    max_tickers_per_group: int = 50,
) -> str:
    """Build HTML body: per-screener ticker lists with change % and rel volume when present."""
    lines: list[str] = [
        "<html><body>",
        f"<p>Run date: <strong>{html.escape(run_date)}</strong></p>",
    ]
    if sheet_id.strip():
        lines.append(
            f'<p>Sheet: <a href="{html.escape(_sheet_url(sheet_id))}">Open Google Sheet</a></p>'
        )
    else:
        lines.append("<p>Sheet: not configured for this run.</p>")
    lines.extend(["<hr/>"])
    if df.empty:
        lines.append("<p>No rows in this run.</p></body></html>")
        return "\n".join(lines)

    if "screener_name" not in df.columns:
        lines.append("<p>(Missing screener_name column.)</p></body></html>")
        return "\n".join(lines)

    sym_col = "symbol" if "symbol" in df.columns else "ticker"
    for name, group in df.groupby("screener_name", sort=True):
        lines.append(f"<h2>{html.escape(str(name))}</h2>")
        lines.append("<ul>")
        sub = group.head(max_tickers_per_group)
        for _, row in sub.iterrows():
            sym = row.get(sym_col, "")
            nm = row.get("name", "")
            chg = row.get("change", "")
            relv = row.get("relative_volume", "")
            if pd.isna(chg):
                chg = ""
            if pd.isna(relv):
                relv = ""
            extra = ""
            if chg != "" or relv != "":
                extra = f" — chg% {chg}, rel vol {relv}"
            lines.append(
                f"<li>{html.escape(str(sym))} ({html.escape(str(nm))})"
                f"{html.escape(extra)}</li>"
            )
        if len(group) > max_tickers_per_group:
            lines.append(
                f"<li><em>… and {len(group) - max_tickers_per_group} more</em></li>"
            )
        lines.append("</ul>")

    lines.append("</body></html>")
    return "\n".join(lines)


def send_screener_summary_html(
    *,
    run_date: str,
    sheet_id: str,
    df: pd.DataFrame,
    smtp_settings: SmtpSettings,
) -> None:
    subject = f"TradingView Screeners – {run_date}"
    body_html = build_html_summary(run_date=run_date, sheet_id=sheet_id, df=df)

    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_settings.mail_from
    msg["To"] = smtp_settings.mail_to

    logger.info(
        "Sending email via %s:%s from %s to %s",
        smtp_settings.host,
        smtp_settings.port,
        smtp_settings.mail_from,
        smtp_settings.mail_to,
    )

    if smtp_settings.port == 465:
        with smtplib.SMTP_SSL(smtp_settings.host, smtp_settings.port, timeout=60) as server:
            server.login(smtp_settings.user, smtp_settings.password)
            server.sendmail(
                smtp_settings.mail_from,
                [smtp_settings.mail_to],
                msg.as_string(),
            )
    else:
        with smtplib.SMTP(smtp_settings.host, smtp_settings.port, timeout=60) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except smtplib.SMTPException:
                logger.warning("STARTTLS failed or not advertised; sending without TLS")
            server.login(smtp_settings.user, smtp_settings.password)
            server.sendmail(
                smtp_settings.mail_from,
                [smtp_settings.mail_to],
                msg.as_string(),
            )
