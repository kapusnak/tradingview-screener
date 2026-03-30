"""Load settings from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional

from dotenv import load_dotenv

# Load .env for local runs; no-op if missing.
load_dotenv()

SheetLayout = Literal["log", "daily"]


def dry_run_from_environment() -> bool:
    """True when DRY_RUN env is set to a truthy value."""
    return _env_bool("DRY_RUN", False)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _optional_json(name: str) -> Optional[Any]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{name} must be valid JSON") from e


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    user: str
    password: str
    mail_from: str
    mail_to: str


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class Settings:
    google_sheets_id: str
    google_service_account_json: Optional[str]
    google_service_account_key_path: Optional[str]
    sheets_enabled: bool
    google_sheet_tab: str
    sheet_layout: SheetLayout
    tradingview_screeners_json: Optional[Any]
    smtp: Optional[SmtpSettings]
    telegram: Optional[TelegramSettings]
    log_level: str
    dry_run_env: bool


def _optional_smtp() -> Optional[SmtpSettings]:
    host = os.environ.get("EMAIL_SMTP_HOST", "").strip()
    port_s = os.environ.get("EMAIL_SMTP_PORT", "587").strip() or "587"
    user = os.environ.get("EMAIL_SMTP_USER", "").strip()
    password = os.environ.get("EMAIL_SMTP_PASS", "").strip()
    mail_from = os.environ.get("EMAIL_FROM", "").strip()
    mail_to = os.environ.get("EMAIL_TO", "").strip()
    if not (user or password or mail_from or mail_to):
        return None
    if not host:
        host = "smtp.gmail.com"
    if not (user and password and mail_from and mail_to):
        raise ValueError(
            "Incomplete SMTP settings: set EMAIL_SMTP_USER, EMAIL_SMTP_PASS, EMAIL_FROM, EMAIL_TO "
            "(and optionally EMAIL_SMTP_HOST), or leave email vars empty to skip email."
        )
    return SmtpSettings(
        host=host,
        port=int(port_s),
        user=user,
        password=password,
        mail_from=mail_from,
        mail_to=mail_to,
    )


def _optional_telegram() -> Optional[TelegramSettings]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token and not chat_id:
        return None
    if not token or not chat_id:
        raise ValueError(
            "Set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or leave both empty to skip Telegram."
        )
    return TelegramSettings(bot_token=token, chat_id=chat_id)


def _validate_google_pair(
    google_sheets_id: str,
    json_str: Optional[str],
    key_path: Optional[str],
) -> bool:
    """Return True if Sheets logging is enabled. Raise if ID and credentials are mismatched."""
    has_id = bool(google_sheets_id)
    has_cred = bool(json_str or key_path)
    if has_id != has_cred:
        if has_id and not has_cred:
            raise ValueError(
                "GOOGLE_SHEETS_ID is set but no service account: set GOOGLE_SERVICE_ACCOUNT_JSON "
                "or GOOGLE_SERVICE_ACCOUNT_KEY_PATH, or clear GOOGLE_SHEETS_ID."
            )
        raise ValueError(
            "Service account is set but GOOGLE_SHEETS_ID is empty: set GOOGLE_SHEETS_ID or remove credentials."
        )
    return has_id and has_cred


def load_settings(*, for_real_run: bool) -> Settings:
    """
    Real runs need at least one output: Google Sheets (ID + SA), SMTP email, or Telegram.
    Dry runs may omit all outputs (fetch + summary only).
    """
    sheet_layout_raw = os.environ.get("SHEET_LAYOUT", "log").strip().lower()
    if sheet_layout_raw not in ("log", "daily"):
        raise ValueError("SHEET_LAYOUT must be 'log' or 'daily'")
    sheet_layout: SheetLayout = sheet_layout_raw  # type: ignore[assignment]

    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip() or None
    key_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY_PATH", "").strip() or None
    if json_str and key_path:
        raise ValueError("Set only one of GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_KEY_PATH")

    google_sheets_id = os.environ.get("GOOGLE_SHEETS_ID", "").strip()
    sheets_enabled = _validate_google_pair(google_sheets_id, json_str, key_path)

    tradingview_screeners_json = _optional_json("TRADINGVIEW_SCREENERS")
    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    dry_run_env = _env_bool("DRY_RUN", False)

    smtp = _optional_smtp()
    telegram = _optional_telegram()

    if for_real_run and not sheets_enabled and smtp is None and telegram is None:
        raise ValueError(
            "Configure at least one output for a real run: "
            "Google Sheets (GOOGLE_SHEETS_ID + service account JSON or key path), "
            "email (SMTP vars), or Telegram (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)."
        )

    return Settings(
        google_sheets_id=google_sheets_id,
        google_service_account_json=json_str,
        google_service_account_key_path=key_path,
        sheets_enabled=sheets_enabled,
        google_sheet_tab=os.environ.get("GOOGLE_SHEET_TAB", "log").strip() or "log",
        sheet_layout=sheet_layout,
        tradingview_screeners_json=tradingview_screeners_json,
        smtp=smtp,
        telegram=telegram,
        log_level=log_level,
        dry_run_env=dry_run_env,
    )
