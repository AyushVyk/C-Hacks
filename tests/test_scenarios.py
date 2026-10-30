import time

import pytest

from sootable import scenarios
from sootable.app import SootableApp
from sootable.store import Store


@pytest.fixture
def app():
    return SootableApp(Store(":memory:"))


def alert_types(app):
    return [a["type"] for a in sorted(app.store.alerts(), key=lambda a: a["created_at"])]


def notified(app):
    return [a["type"] for a in app.store.alerts() if a["delivered"]]


def test_steady_healthy_no_alerts(app):
    scenarios.run(app, "steady_healthy")
    assert len(app.store.readings()) == 60
    assert app.store.alerts() == []


def test_slow_rise_each_alert_notified_once_in_order(app):
    scenarios.run(app, "slow_rise")
    assert alert_types(app)[:3] == ["WATCH", "RISE", "OVER"]
    assert sorted(notified(app)) == ["OVER", "RISE", "WATCH"]  # exactly three notifications


def test_sudden_spike_is_not_an_alarm(app):
    from sootable import engine
    scenarios.run(app, "sudden_spike")
    assert "OVER" not in alert_types(app)
    s = engine.summary(app.store, time.time())
    assert s["note"] == "One high reading today, check again tomorrow."
    assert s["status"] == "OK"


def test_noisy_does_not_flap(app):
    scenarios.run(app, "noisy")
    assert notified(app) == []


def test_split_frames_all_readings_arrive(app):
    scenarios.run(app, "split_frames")
    assert len(app.store.readings()) == 60


def test_crc_corruption_dropped_and_nothing_lost(app):
    info = scenarios.run(app, "crc_corruption")
    assert info["sync"]["complete"]
    assert len(app.store.readings()) == 60
    assert any("CRC mismatch" in e["note"] for e in app.inspector.entries)


def test_drop_mid_sync_then_repeat_has_no_duplicates(app):
    info = scenarios.run(app, "drop_mid_sync")
    assert not info["first_sync"]["complete"]
    assert info["sync"]["complete"]
    assert len(app.store.readings()) == 60
    assert app.device.records == []  # everything acknowledged and freed


def test_epoch_change_keeps_both_epochs_ordered(app):
    scenarios.run(app, "epoch_change")
    rows = app.store.readings()
    assert len(rows) == 60
    assert {r["epoch"] for r in rows} == {1, 2}
    assert [r["taken_at"] for r in rows] == sorted(r["taken_at"] for r in rows)
    assert min(r["seq"] for r in rows if r["epoch"] == 2) == 0


def test_no_reference_is_stored_invalid_and_leaves_gaps(app):
    from sootable import engine
    scenarios.run(app, "no_reference")
    rows = app.store.readings()
    assert len(rows) == 60 and sum(1 for r in rows if not r["valid"]) == 4
    assert len(engine.daily_k(app.store)) == 56


def test_saturation_is_invalid_with_reason(app):
    scenarios.run(app, "saturation")
    bad = [r for r in app.store.readings() if not r["valid"]]
    assert len(bad) == 3 and all(r["reason"] == "Sensor saturated" for r in bad)


def test_measure_now_adds_a_reading_and_second_sync_is_empty(app):
    scenarios.run(app, "steady_healthy")
    app.device.current_k = 2.0
    app.measure()
    rows = app.store.readings()
    assert len(rows) == 61 and rows[-1]["k"] == pytest.approx(2.0, abs=0.05)
    app.sync()
    assert len(app.store.readings()) == 61


def test_forecast_only_when_heading_for_a_limit_still_ahead(app):
    from sootable import engine
    now = time.time()
    scenarios.run(app, "wearing_out")
    s = engine.summary(app.store, now)
    assert s["status"] == "WATCH" and s["streak"] == 120 and s["today_done"]
    assert s["forecast"] and 20 <= s["forecast"]["days"] <= 90 and s["forecast"]["per_month"] > 0.1
    for name in ("steady_healthy", "slow_rise", "noisy"):  # steady, already over, and noisy-but-flat
        scenarios.run(app, name)
        assert engine.summary(app.store, now)["forecast"] is None, name


def test_cleaning_reminder_starts_after_sample_history_and_comes_back(app):
    from sootable import engine
    scenarios.run(app, "steady_healthy")
    assert not engine.summary(app.store, time.time())["clean_reminder"]
    for _ in range(30):                                   # thirty more readings on the same sensor
        app.measure()
    assert engine.summary(app.store, time.time())["clean_reminder"]


def test_streak_breaks_on_a_missed_day():
    from datetime import date
    from sootable import engine
    today = date(2026, 10, 30)
    days = {f"2026-10-{d}": 1.4 for d in (30, 29, 28, 26, 25)}  # nothing on the 27th
    assert engine.streak(days, today) == 3
    assert engine.streak({"2026-10-29": 1.4, "2026-10-28": 1.4}, today) == 2  # today not done yet
    assert engine.streak({}, today) == 0


def test_chamber_length_comes_from_the_device(app):
    scenarios.run(app, "steady_healthy")
    assert app.session.path_len_m == 0.10  # reported in the device's HELLO frame (100 mm)
    assert app.store.vehicle()["limit_k"] == 2.45
