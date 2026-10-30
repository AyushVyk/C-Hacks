import time

import pytest
from fastapi.testclient import TestClient

from sootable.app import DEVICE_ID, SootableApp
from sootable.device_sim import ADV_NAME, FLEET, FW, L_MM
from sootable.store import Store

SECOND_ID, SECOND_NAME = FLEET[1]


@pytest.fixture
def app():
    return SootableApp(Store(":memory:"))


def test_a_scan_lists_every_meter_in_range_the_way_a_bluetooth_scan_would(app):
    found = app.scan()
    assert [d["name"] for d in found] == [name for _, name in FLEET]
    assert all(-100 < d["rssi"] < -30 for d in found)
    assert all(d["vehicle"] is None for d in found)       # none is paired to a vehicle yet
    assert not app.is_paired()                            # looking is not pairing


def test_scan_shows_which_vehicle_a_meter_is_already_on(app):
    app.store.rename_vehicle("Swift")
    app.pair(DEVICE_ID)
    on = {d["id"]: d["vehicle"] for d in app.scan()}
    assert on[DEVICE_ID] == "Swift" and on[SECOND_ID] is None


def test_scan_does_not_disturb_the_readings(app):
    """The advertisement uses its own random numbers, so the same demo always gives the same readings."""
    a, b = SootableApp(Store(":memory:")), SootableApp(Store(":memory:"))
    b.scan(); b.scan()
    for x in (a, b):
        x.device.record(1.4, 1_000_000)
    assert a.device.records == b.device.records


def test_pairing_runs_the_handshake_and_records_what_the_meter_reports(app):
    vid = app.store.active_vehicle_id()
    result = app.pair(DEVICE_ID)
    assert result["complete"] and app.is_paired() and app.meter_for(vid) == DEVICE_ID
    row = app.store.device(DEVICE_ID)
    assert row["name"] == ADV_NAME and row["fw"] == FW and row["vehicle_id"] == vid
    assert int(app.store.get_setting(f"chamber_mm:{DEVICE_ID}")) == L_MM   # from the HELLO frame, not hard-coded


def test_pairing_with_a_meter_that_is_not_in_range_fails(app):
    with pytest.raises(LookupError):
        app.pair("SOME-OTHER-METER")
    assert not app.is_paired()


def test_each_vehicle_gets_its_own_meter(app):
    first = app.store.active_vehicle_id()
    second = app.store.add_vehicle("Second car")
    app.pair(DEVICE_ID, first)
    app.pair(SECOND_ID, second)
    assert app.meter_for(first) == DEVICE_ID and app.meter_for(second) == SECOND_ID
    assert app.is_paired(first) and app.is_paired(second)


def test_a_vehicle_has_one_meter_so_pairing_another_replaces_it(app):
    vid = app.store.active_vehicle_id()
    app.pair(DEVICE_ID, vid)
    app.pair(SECOND_ID, vid)
    assert app.meter_for(vid) == SECOND_ID
    assert app.store.device(DEVICE_ID) is None            # the replaced meter is forgotten


def test_moving_a_meter_syncs_it_first_so_waiting_readings_stay_with_the_old_vehicle(app):
    first = app.store.active_vehicle_id()
    second = app.store.add_vehicle("Second car")
    app.pair(DEVICE_ID, first)
    app.device.record(1.4, time.time() - 3600)            # a reading waiting on the meter, taken on the first vehicle
    app.pair(DEVICE_ID, second)                           # the meter is moved to the second vehicle
    assert len(app.store.readings(first)) == 1 and app.store.readings(second) == []
    assert app.meter_for(first) is None and app.meter_for(second) == DEVICE_ID


def test_demo_data_for_a_second_vehicle_leaves_the_first_alone(app):
    from sootable import scenarios
    first = app.store.active_vehicle_id()
    scenarios.run(app, "steady_healthy")
    before, alerts_before = len(app.store.readings(first)), app.store.alerts(first)
    second = app.store.add_vehicle("Second car")
    scenarios.run(app, "wearing_out", second, keep=True)
    assert len(app.store.readings(first)) == before and app.store.alerts(first) == alerts_before
    assert len(app.store.readings(second)) == 120
    assert app.meter_for(first) == DEVICE_ID and app.meter_for(second) == SECOND_ID   # a free meter was used
    assert {r["device_id"] for r in app.store.readings(second)} == {SECOND_ID}
    assert app.demo == {first: "steady_healthy", second: "wearing_out"}
    assert app.store.active_vehicle_id() == second


def test_running_demo_data_again_for_a_vehicle_replaces_its_data(app):
    from sootable import scenarios
    second = app.store.add_vehicle("Second car")
    scenarios.run(app, "wearing_out", second, keep=True)
    scenarios.run(app, "steady_healthy", second, keep=True)
    assert len(app.store.readings(second)) == 60 and app.demo[second] == "steady_healthy"
    assert len(app.store.devices()) == 1                  # the replaced meter was freed, not leaked


def test_demo_data_needs_a_free_demo_meter(app):
    from sootable import scenarios
    vehicles = [app.store.active_vehicle_id()] + [app.store.add_vehicle(f"Car {i}") for i in (2, 3, 4)]
    for vid, (device_id, _) in zip(vehicles, FLEET):
        app.pair(device_id, vid)                          # all three meters are in use
    with pytest.raises(LookupError):
        scenarios.run(app, "steady_healthy", vehicles[3], keep=True)


def test_a_vehicle_without_a_meter_cannot_take_a_reading(app):
    with pytest.raises(LookupError):
        app.measure()


def test_forgetting_the_meter_keeps_readings_but_unpairs(app):
    app.pair(DEVICE_ID)
    app.measure()
    assert len(app.store.readings()) == 1
    app.forget_meter(DEVICE_ID)
    assert not app.is_paired() and app.store.device(DEVICE_ID) is None
    assert len(app.store.readings()) == 1


def test_a_database_from_the_single_meter_version_keeps_its_paired_meter(tmp_path):
    import sqlite3
    from sootable.store import SCHEMA_V1, SCHEMA_V2, SCHEMA_V3
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    for sql in (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3):
        old.executescript(sql)
    old.execute("CREATE TABLE migrations (version INTEGER PRIMARY KEY)")
    old.executemany("INSERT INTO migrations VALUES (?)", [(1,), (2,), (3,)])
    old.execute("INSERT INTO vehicle (id, name, limit_k, path_len_m, created_at, kind) VALUES (1, 'Old car', 2.45, 0.1, 0, 'car')")
    old.execute("INSERT INTO device (id, name, last_epoch, last_seen_at, fw, vehicle_id) VALUES ('SOOT-SIM-01', 'SootAble-7F2A', 1, 1000, 1, 1)")
    old.execute("INSERT INTO setting VALUES ('paired_device', 'SOOT-SIM-01')")
    old.commit()
    old.close()
    store = Store(path)
    assert [d["id"] for d in store.devices()] == ["SOOT-SIM-01"]
    assert store.device_for_vehicle(1)["name"] == "SootAble-7F2A"
    assert store.get_setting("paired_device") is None


# ---- through the HTTP API ----
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SOOTABLE_DB", ":memory:")
    from sootable import server
    monkeypatch.setattr(server, "state", SootableApp(Store(":memory:")))
    return TestClient(server.app)


def test_nothing_can_be_measured_or_synced_until_a_meter_is_paired(client):
    assert client.post("/api/measure").status_code == 409
    assert client.post("/api/sync").status_code == 409
    s = client.get("/api/state").json()
    assert s["device"]["paired"] is False and s["device"]["name"] is None and s["device"]["last_sync"] is None


def test_scan_pair_measure_forget_over_the_api(client):
    devices = client.get("/api/scan").json()["devices"]
    assert len(devices) == len(FLEET)
    s = client.post("/api/pair", json={"id": devices[0]["id"]}).json()
    d = s["device"]
    assert d["paired"] and d["name"] == ADV_NAME and d["fw"] == FW and d["chamber_mm"] == L_MM and d["last_sync"]
    assert client.post("/api/measure").json()["reading_count"] == 1
    assert client.delete(f"/api/meters/{devices[0]['id']}").json()["device"]["paired"] is False
    assert client.post("/api/measure").status_code == 409
    assert client.post("/api/pair", json={"id": "nope"}).status_code == 404
    assert client.post("/api/pair", json={"id": devices[0]["id"], "vehicle_id": 999}).status_code == 404


def test_adding_a_vehicle_then_pairing_its_own_meter(client):
    client.post("/api/onboarding", json={"name": "Swift"})
    client.post("/api/pair", json={"id": DEVICE_ID})
    s = client.post("/api/vehicles", json={"name": "Dzire"}).json()
    assert s["device"]["paired"] is False                  # the new vehicle has no meter yet
    assert client.post("/api/measure").status_code == 409  # so it cannot take a reading
    second = s["vehicle"]["id"]
    s = client.post("/api/pair", json={"id": SECOND_ID, "vehicle_id": second}).json()
    assert s["vehicle"]["id"] == second and s["device"]["name"] == FLEET[1][1]
    assert {v["name"]: v["meter"] for v in s["vehicles"]} == {"Swift": ADV_NAME, "Dzire": FLEET[1][1]}
    assert client.post("/api/measure").json()["reading_count"] == 1


def test_adding_a_vehicle_then_using_demo_data_for_it_over_the_api(client):
    client.post("/api/onboarding", json={"name": "Swift"})
    client.post("/api/scenario", json={"name": "steady_healthy"})
    first = client.get("/api/state").json()["vehicle"]["id"]
    second = client.post("/api/vehicles", json={"name": "Dzire"}).json()["vehicle"]["id"]
    s = client.post("/api/scenario", json={"name": "wearing_out", "vehicle_id": second, "keep": True}).json()
    assert s["vehicle"]["id"] == second and s["reading_count"] == 120 and s["scenario"] == "wearing_out"
    assert s["device"]["paired"] and s["device"]["name"] == FLEET[1][1]
    s = client.post("/api/vehicles/select", json={"id": first}).json()
    assert s["reading_count"] == 60 and s["scenario"] == "steady_healthy"    # the first vehicle is intact
    assert client.post("/api/scenario", json={"name": "x", "vehicle_id": second, "keep": True}).status_code == 404
    assert client.post("/api/scenario", json={"name": "steady_healthy", "vehicle_id": 999, "keep": True}).status_code == 404


def test_demo_data_counts_as_a_paired_meter_and_delete_all_unpairs(client):
    s = client.post("/api/scenario", json={"name": "steady_healthy"}).json()
    assert s["device"]["paired"] and s["device"]["name"] == ADV_NAME
    assert client.post("/api/measure").status_code == 200
    assert client.delete("/api/data").json()["device"]["paired"] is False
