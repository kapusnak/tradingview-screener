"""Load settings from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal

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


def _require(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise ValueError(f"Missing required environment variable: {name}")
    return v


def _optional_json(name: str) -> Any | None:
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
class Settings:
    google_sheets_id: str
    google_service_account_json: str | None
    google_service_account_key_path: str | None
    google_sheet_tab: str
    sheet_layout: SheetLayout
    tradingview_screeners_json: Any | None
    smtp: SmtpSettings
    log_level: str
    dry_run_env: bool


def load_settings(*, for_real_run: bool) -> Settings:
    """
    If for_real_run is True (normal run, not --dry-run), Google and SMTP
    settings are required. Otherwise they may be omitted for local smoke tests.
    """
    sheet_layout_raw = os.environ.get("SHEET_LAYOUT", "log").strip().lower()
    if sheet_layout_raw not in ("log", "daily"):
        raise ValueError("SHEET_LAYOUT must be 'log' or 'daily'")
    sheet_layout: SheetLayout = sheet_layout_raw  # type: ignore[assignment]

    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip() or None
    key_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY_PATH", "").strip() or None
    if json_str and key_path:
        raise ValueError("Set only one of GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_KEY_PATH")

    tradingview_screeners_json = _optional_json("TRADINGVIEW_SCREENERS")

    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    dry_run_env = _env_bool("DRY_RUN", False)

    if not for_real_run:
        return Settings(
            google_sheets_id=os.environ.get("GOOGLE_SHEETS_ID", "").strip(),
            google_service_account_json=json_str,
            google_service_account_key_path=key_path,
            google_sheet_tab=os.environ.get("GOOGLE_SHEET_TAB", "log").strip() or "log",
            sheet_layout=sheet_layout,
            tradingview_screeners_json=tradingview_screeners_json,
            smtp=SmtpSettings(
                host=os.environ.get("EMAIL_SMTP_HOST", "").strip(),
                port=int(os.environ.get("EMAIL_SMTP_PORT", "587") or "587"),
                user=os.environ.get("EMAIL_SMTP_USER", "").strip(),
                password=os.environ.get("EMAIL_SMTP_PASS", "").strip(),
                mail_from=os.environ.get("EMAIL_FROM", "").strip(),
                mail_to=os.environ.get("EMAIL_TO", "").strip(),
            ),
            log_level=log_level,
            dry_run_env=dry_run_env,
        )

    google_sheets_id = _require("GOOGLE_SHEETS_ID")
    if not json_str and not key_path:
        raise ValueError(
            "Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_KEY_PATH for a real run"
        )

    smtp = SmtpSettings(
        host=_require("EMAIL_SMTP_HOST"),
        port=int(os.environ.get("EMAIL_SMTP_PORT", "587") or "587"),
        user=_require("EMAIL_SMTP_USER"),
        password=_require("EMAIL_SMTP_PASS"),
        mail_from=_require("EMAIL_FROM"),
        mail_to=_require("EMAIL_TO"),
    )

    return Settings(
        google_sheets_id=google_sheets_id,
        google_service_account_json=json_str,
        google_service_account_key_path=key_path,
        google_sheet_tab=os.environ.get("GOOGLE_SHEET_TAB", "log").strip() or "log",
        sheet_layout=sheet_layout,
        tradingview_screeners_json=tradingview_screeners_json,
        smtp=smtp,
        log_level=log_level,
        dry_run_env=dry_run_env,
    )
