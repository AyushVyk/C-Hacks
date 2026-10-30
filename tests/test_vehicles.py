import sqlite3
import time

import pytest

from sootable import engine, scenarios
from sootable.app import DEVICE_ID, SootableApp
from sootable.device_sim import FLEET
from sootable.store import SCHEMA_V1, Store

SECOND_ID = FLEET[1][0]


@pytest.fixture
def app():
    return SootableApp(Store(":memory:"))


def test_each_vehicle_keeps_its_own_readings_and_status(app):
    first = app.store.active_vehicle_id()
    scenarios.run(app, "steady_healthy")                  # 60 healthy days on the first vehicle
    second = app.store.add_vehicle("Second car")
    app.pair(SECOND_ID, second)                           # the second vehicle has its own meter
    app.meters[SECOND_ID].device.current_k = 3.0
    app.measure(second)                                   # one smoky reading, with the second vehicle's meter
    assert len(app.store.readings(first)) == 60
    assert len(app.store.readings(second)) == 1
    now = time.time()
    a, b = engine.summary(app.store, now, first), engine.summary(app.store, now, second)
    assert a["status"] == "OK" and a["reading_count"] == 60
    assert b["reading_count"] == 1 and b["status"] is None    # one day is not a trend yet
    assert b["latest"]["k"] == pytest.approx(3.0, abs=0.05)


def test_syncing_sends_each_meters_readings_to_its_own_vehicle(app):
    first = app.store.active_vehicle_id()
    second = app.store.add_vehicle("Second car")
    app.pair(DEVICE_ID, first)
    app.pair(SECOND_ID, second)
    app.meters[DEVICE_ID].device.record(1.4, time.time() - 120)
    app.meters[SECOND_ID].device.record(2.2, time.time() - 60)
    app.meters[SECOND_ID].device.record(2.3, time.time() - 30)
    result = app.sync()                                   # syncs every paired meter
    assert result["complete"]
    assert len(app.store.readings(first)) == 1 and len(app.store.readings(second)) == 2
    assert {r["device_id"] for r in app.store.readings(second)} == {SECOND_ID}


def test_alerts_and_baselines_are_per_vehicle(app):
    first = app.store.active_vehicle_id()
    scenarios.run(app, "slow_rise")
    second = app.store.add_vehicle("Quiet car")
    assert {a["type"] for a in app.store.alerts(first)} == {"WATCH", "RISE", "OVER"}
    assert app.store.alerts(second) == []
    assert app.store.vget(first, "baseline_k") is not None and app.store.vget(second, "baseline_k") is None
    new = engine.refresh_alerts(app.store)
    assert new == []                                      # nothing new, and nothing leaks across vehicles


def test_new_alerts_say_which_vehicle(app):
    app.store.rename_vehicle("Swift")
    result = scenarios.run(app, "slow_rise")
    notified = result["sync"]["alerts"]
    assert notified and all(a["vehicle"] == "Swift" and a["vehicle_id"] == app.store.active_vehicle_id() for a in notified)


def test_removing_a_vehicle_removes_its_data_and_frees_its_meter(app):
    first = app.store.active_vehicle_id()
    second = app.store.add_vehicle("Second car")
    app.pair(SECOND_ID, second)
    app.measure(second)
    app.store.vset(second, "baseline_from", "2026-01-01")
    assert app.store.delete_vehicle(second)
    assert app.store.readings(second) == [] and app.store.vget(second, "baseline_from") is None
    assert [v["id"] for v in app.store.vehicles()] == [first]
    assert app.store.device(SECOND_ID) is None            # the meter is free to be paired again
    assert app.store.active_vehicle_id() == first
    assert not app.store.delete_vehicle(first)            # the last one stays


def test_delete_all_returns_to_a_single_fresh_vehicle(app):
    app.store.add_vehicle("Second car")
    app.store.set_setting("onboarded", "1")
    app.reset(wipe=True)
    assert len(app.store.vehicles()) == 1 and app.store.get_setting("onboarded") is None


def test_sample_scenarios_keep_vehicles_and_first_run_flag(app):
    app.store.add_vehicle("Second car")
    app.store.set_setting("onboarded", "1")
    scenarios.run(app, "steady_healthy")
    assert len(app.store.vehicles()) == 2 and app.store.get_setting("onboarded") == "1"


def test_vehicle_cards_for_the_switcher(app):
    scenarios.run(app, "wearing_out")
    second = app.store.add_vehicle("Second car")
    cards = {c["name"]: c for c in engine.vehicle_cards(app.store, time.time())}
    assert cards["My vehicle"]["status"] == "WATCH" and cards["My vehicle"]["meter"] == "SootAble-7F2A"
    assert cards["Second car"]["reading_count"] == 0 and cards["Second car"]["meter"] is None
    assert cards["Second car"]["id"] == second


def test_a_single_vehicle_database_upgrades(tmp_path):
    """A database made before vehicles existed keeps its readings and alerts on vehicle 1."""
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(SCHEMA_V1)
    old.execute("CREATE TABLE migrations (version INTEGER PRIMARY KEY)")
    old.execute("INSERT INTO migrations VALUES (1)")
    old.execute("INSERT INTO vehicle VALUES (1, 'Old car', 2.45, 0.1, 0)")
    old.execute("INSERT INTO reading (device_id, epoch, seq, taken_at, received_at, i0, i, flags, k, valid)"
                " VALUES ('D', 1, 0, 1000, 1000, 920, 800, 0, 1.4, 1)")
    old.execute("INSERT INTO alert (created_at, day, type, k_smooth, message, delivered)"
                " VALUES (1000, '2026-01-01', 'WATCH', 2.0, 'm', 1)")
    old.commit()
    old.close()
    store = Store(path)
    assert [r["vehicle_id"] for r in store.readings()] == [1]
    assert [a["vehicle_id"] for a in store.alerts()] == [1]
    assert store.vehicle()["name"] == "Old car" and store.vehicle()["kind"] == "car"
    store.add_alert(2000, "2026-01-01", "WATCH", 2.0, "m", True, store.add_vehicle("New car"))  # same day and type
    assert len(store.alerts()) == 2
