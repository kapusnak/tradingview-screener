from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.morning_run import should_send_morning_charts

UTC = ZoneInfo("UTC")


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_cest_slot_sends_at_0500_utc() -> None:
    # 2026-07-15 Wednesday; CEST = UTC+2 → 05:00 UTC = 07:00 Prague
    ok, reason = should_send_morning_charts(_utc(2026, 7, 15, 5, 0))
    assert ok, reason
    assert "Wednesday" in reason


def test_cest_off_slot_at_0600_utc_is_skipped() -> None:
    ok, reason = should_send_morning_charts(_utc(2026, 7, 15, 6, 0))
    assert not ok
    assert "outside 07:00–07:59" in reason


def test_cet_slot_sends_at_0600_utc() -> None:
    # 2026-01-16 Friday; CET = UTC+1 → 06:00 UTC = 07:00 Prague
    ok, reason = should_send_morning_charts(_utc(2026, 1, 16, 6, 0))
    assert ok, reason
    assert "Friday" in reason


def test_cet_off_slot_at_0500_utc_is_skipped() -> None:
    ok, reason = should_send_morning_charts(_utc(2026, 1, 16, 5, 0))
    assert not ok
    assert "outside 07:00–07:59" in reason


def test_saturday_is_skipped_even_at_pragues_700() -> None:
    # 2026-01-17 Saturday 06:00 UTC = 07:00 CET
    ok, reason = should_send_morning_charts(_utc(2026, 1, 17, 6, 0))
    assert not ok
    assert "weekend" in reason
    assert "Saturday" in reason


def test_sunday_cest_is_skipped() -> None:
    # 2026-07-12 Sunday 05:00 UTC = 07:00 CEST
    ok, reason = should_send_morning_charts(_utc(2026, 7, 12, 5, 0))
    assert not ok
    assert "weekend" in reason
    assert "Sunday" in reason


def test_force_overrides_weekend_and_hour() -> None:
    ok, reason = should_send_morning_charts(_utc(2026, 1, 17, 12, 0), force=True)
    assert ok
    assert reason.startswith("forced send")


def test_naive_datetime_treated_as_utc() -> None:
    ok, reason = should_send_morning_charts(datetime(2026, 1, 16, 6, 0))
    assert ok, reason


def test_main_skips_without_telegram_env_when_outside_window(monkeypatch) -> None:
    from src import morning_run

    monkeypatch.setattr(
        morning_run,
        "should_send_morning_charts",
        lambda now, force=False: (False, "weekend in Europe/Prague"),
    )
    assert morning_run.main([]) == 0
