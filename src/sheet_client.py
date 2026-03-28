"""Google Sheets via gspread — log tab (Pattern A) or daily worksheet (Pattern B)."""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from src.config import Settings

logger = logging.getLogger(__name__)

SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)


def _gspread_client(settings: Settings) -> gspread.Client:
    if settings.google_service_account_json:
        info = json.loads(settings.google_service_account_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    elif settings.google_service_account_key_path:
        creds = Credentials.from_service_account_file(
            settings.google_service_account_key_path,
            scopes=SCOPES,
        )
    else:
        raise ValueError("No Google service account JSON or key path configured")
    return gspread.authorize(creds)


def _ensure_worksheet(sh: gspread.Spreadsheet, title: str, rows: int = 2000, cols: int = 30):
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        logger.info("Creating worksheet %r", title)
        return sh.add_worksheet(title=title, rows=str(rows), cols=str(cols))


def _delete_rows_matching_run_date(
    ws: gspread.Worksheet,
    run_date: str,
    *,
    run_date_col: int = 0,
) -> None:
    """
    Idempotency for Pattern A: remove data rows (not header) where run_date matches.

    Assumes first row is header and column index run_date_col holds run_date (ISO string).
    Deletes from highest row index downward so indices stay valid.
    """
    values = ws.get_all_values()
    if len(values) <= 1:
        return
    header = values[0]
    if run_date_col >= len(header):
        logger.warning("run_date column index %s past header width; skipping row delete", run_date_col)
        return
    to_delete: list[int] = []
    for i, row in enumerate(values[1:], start=2):  # 1-based sheet rows; skip header
        if len(row) <= run_date_col:
            continue
        if row[run_date_col].strip() == run_date:
            to_delete.append(i)
    for row_idx in sorted(to_delete, reverse=True):
        ws.delete_rows(row_idx)


def _write_headers_if_needed(ws: gspread.Worksheet, columns: Sequence[str]) -> None:
    existing = ws.get_all_values()
    if not existing or not any(cell.strip() for cell in existing[0]):
        ws.update(range_name="A1", values=[list(columns)], value_input_option="USER_ENTERED")
        logger.info("Wrote header row")
        return
    first = existing[0]
    if list(first)[: len(columns)] != list(columns):
        logger.warning(
            "Existing header %s does not match expected %s; leaving header as-is",
            first[: len(columns)],
            list(columns),
        )


def write_dataframe_log_tab(
    settings: Settings,
    df: pd.DataFrame,
    run_date: str,
) -> None:
    """
    Pattern A: single worksheet (settings.google_sheet_tab).

    Before append, delete all rows whose run_date column equals this run's date (same calendar
    day re-run replaces that slice; no duplicate rows for the day).
    """
    if df.empty:
        logger.warning("Empty DataFrame; nothing to write to sheet")
        return

    gc = _gspread_client(settings)
    sh = gc.open_by_key(settings.google_sheets_id)
    ws = _ensure_worksheet(sh, settings.google_sheet_tab)

    columns = list(df.columns)
    # run_date must be first column for _delete_rows_matching_run_date
    if columns[0] != "run_date":
        logger.warning("Expected first column 'run_date' for idempotent delete; found %r", columns[0])

    _write_headers_if_needed(ws, columns)
    _delete_rows_matching_run_date(ws, run_date, run_date_col=0)

    records = df.astype(object).where(pd.notna(df), "").values.tolist()
    rows = [[_cell_str(v) for v in row] for row in records]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info("Appended %s rows to worksheet %r", len(rows), settings.google_sheet_tab)


def _cell_str(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    return str(v)


def write_dataframe_daily_tab(
    settings: Settings,
    df: pd.DataFrame,
    run_date: str,
) -> None:
    """
    Pattern B: worksheet title = run_date (YYYY-MM-DD). Full replace: clear body and rewrite.

    Re-running the same day overwrites the entire tab contents (idempotent for that day).
    """
    if df.empty:
        logger.warning("Empty DataFrame; nothing to write to daily sheet")
        return

    gc = _gspread_client(settings)
    sh = gc.open_by_key(settings.google_sheets_id)
    ws = _ensure_worksheet(sh, run_date)

    columns = list(df.columns)
    ws.clear()
    ws.update(range_name="A1", values=[columns], value_input_option="USER_ENTERED")
    records = df.astype(object).where(pd.notna(df), "").values.tolist()
    rows = [[_cell_str(v) for v in row] for row in records]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    logger.info("Wrote %s rows to daily worksheet %r", len(rows), run_date)


def write_dataframe(settings: Settings, df: pd.DataFrame, run_date: str) -> None:
    if settings.sheet_layout == "daily":
        write_dataframe_daily_tab(settings, df, run_date)
    else:
        write_dataframe_log_tab(settings, df, run_date)
