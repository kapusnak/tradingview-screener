from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.run import should_send_evening_scan

UTC = ZoneInfo("UTC")


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_edt_regular_sends_at_1930_utc() -> None:
    # 2026-07-15 Wednesday; EDT = UTC-4 → 19:30 UTC = 15:30 ET, close 16:00
    ok, reason = should_send_evening_scan(_utc(2026, 7, 15, 19, 30))
    assert ok, reason
    assert "Wednesday" in reason
    assert "15:30" in reason


def test_edt_regular_off_slot_at_2030_utc_is_skipped() -> None:
    ok, reason = should_send_evening_scan(_utc(2026, 7, 15, 20, 30))
    assert not ok
    assert "outside NYSE pre-close window" in reason


def test_est_regular_sends_at_2030_utc() -> None:
    # 2026-01-16 Friday; EST = UTC-5 → 20:30 UTC = 15:30 ET
    ok, reason = should_send_evening_scan(_utc(2026, 1, 16, 20, 30))
    assert ok, reason
    assert "Friday" in reason
    assert "15:30" in reason


def test_est_regular_off_slot_at_1930_utc_is_skipped() -> None:
    ok, reason = should_send_evening_scan(_utc(2026, 1, 16, 19, 30))
    assert not ok
    assert "outside NYSE pre-close window" in reason


def test_eu_us_dst_gap_after_eu_fallback_sends_at_1930_utc() -> None:
    # EU winter from 2026-10-25; US DST until 2026-11-01.
    # 2026-10-26 Monday 19:30 UTC = 15:30 EDT = 20:30 CET (not 21:30 Prague).
    ok, reason = should_send_evening_scan(_utc(2026, 10, 26, 19, 30))
    assert ok, reason
    assert "Monday" in reason


def test_eu_us_dst_gap_2030_utc_is_the_off_slot() -> None:
    ok, reason = should_send_evening_scan(_utc(2026, 10, 26, 20, 30))
    assert not ok
    assert "outside NYSE pre-close window" in reason


def test_spring_dst_gap_sends_at_1930_utc() -> None:
    # US DST from 2026-03-08; EU still CET until 2026-03-29.
    ok, reason = should_send_evening_scan(_utc(2026, 3, 9, 19, 30))
    assert ok, reason


def test_thanksgiving_is_skipped() -> None:
    # 2026-11-26 Thursday; 20:30 UTC would be 15:30 EST on a normal day
    ok, reason = should_send_evening_scan(_utc(2026, 11, 26, 20, 30))
    assert not ok
    assert "US market closed" in reason


def test_day_after_thanksgiving_sends_at_1730_utc() -> None:
    # 2026-11-27 Friday early close 13:00 EST → send 12:30 EST = 17:30 UTC
    ok, reason = should_send_evening_scan(_utc(2026, 11, 27, 17, 30))
    assert ok, reason
    assert "12:30" in reason
    assert "13:00" in reason


def test_day_after_thanksgiving_regular_slot_is_skipped() -> None:
    ok, reason = should_send_evening_scan(_utc(2026, 11, 27, 20, 30))
    assert not ok
    assert "outside NYSE pre-close window" in reason


def test_christmas_eve_sends_at_1730_utc() -> None:
    ok, reason = should_send_evening_scan(_utc(2026, 12, 24, 17, 30))
    assert ok, reason
    assert "12:30" in reason


def test_july3_edt_early_close_sends_at_1630_utc() -> None:
    # 2025-07-03 Thursday; Independence Day Friday → 13:00 EDT close
    ok, reason = should_send_evening_scan(_utc(2025, 7, 3, 16, 30))
    assert ok, reason
    assert "12:30" in reason


def test_july3_2026_observed_independence_day_is_closed() -> None:
    ok, reason = should_send_evening_scan(_utc(2026, 7, 3, 19, 30))
    assert not ok
    assert "US market closed" in reason


def test_saturday_is_skipped() -> None:
    ok, reason = should_send_evening_scan(_utc(2026, 1, 17, 20, 30))
    assert not ok
    assert "US market closed" in reason
    assert "Saturday" in reason


def test_regular_est_day_only_2030_utc_slot_sends() -> None:
    slots = [(16, 30), (17, 30), (19, 30), (20, 30)]
    results = [should_send_evening_scan(_utc(2026, 1, 16, h, m))[0] for h, m in slots]
    assert results == [False, False, False, True]


def test_regular_edt_day_only_1930_utc_slot_sends() -> None:
    slots = [(16, 30), (17, 30), (19, 30), (20, 30)]
    results = [should_send_evening_scan(_utc(2026, 7, 15, h, m))[0] for h, m in slots]
    assert results == [False, False, True, False]


def test_early_close_est_only_1730_utc_slot_sends() -> None:
    slots = [(16, 30), (17, 30), (19, 30), (20, 30)]
    results = [should_send_evening_scan(_utc(2026, 11, 27, h, m))[0] for h, m in slots]
    assert results == [False, True, False, False]


def test_window_excludes_close_and_before_send() -> None:
    ok_before, _ = should_send_evening_scan(_utc(2026, 7, 15, 19, 29))
    ok_at_close, _ = should_send_evening_scan(_utc(2026, 7, 15, 20, 0))
    ok_late, reason = should_send_evening_scan(_utc(2026, 7, 15, 19, 45))
    assert not ok_before
    assert not ok_at_close
    assert ok_late, reason


def test_force_overrides_holiday_and_hour() -> None:
    ok, reason = should_send_evening_scan(_utc(2026, 11, 26, 12, 0), force=True)
    assert ok
    assert reason.startswith("forced send")


def test_naive_datetime_treated_as_utc() -> None:
    ok, reason = should_send_evening_scan(datetime(2026, 1, 16, 20, 30))
    assert ok, reason


def test_main_skips_without_telegram_env_when_outside_window(monkeypatch) -> None:
    from src import run

    monkeypatch.setattr(
        run,
        "should_send_evening_scan",
        lambda now, force=False: (False, "US market closed"),
    )
    assert run.main([]) == 0
