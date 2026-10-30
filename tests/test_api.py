import os

os.environ["SOOTABLE_DB"] = ":memory:"

from fastapi.testclient import TestClient  # noqa: E402

from sootable.server import app  # noqa: E402

client = TestClient(app)


def test_slow_rise_through_the_api():
    r = client.post("/api/scenario", json={"name": "slow_rise"})
    assert r.status_code == 200
    s = r.json()
    assert s["status"] == "OVER" and s["reading_count"] == 60
    assert [a["type"] for a in s["new_alerts"]] == ["WATCH", "RISE", "OVER"]
    assert len(s["chart"]) == 30 and "limit 2.45" in s["chart_text"]


def test_measure_inspector_history_and_csv():
    client.post("/api/scenario", json={"name": "steady_healthy"})
    client.post("/api/sim/level", json={"k": 2.0, "flags": 0})
    s = client.post("/api/measure").json()
    assert s["reading_count"] == 61
    entries = client.get("/api/inspector").json()["entries"]
    assert any("TRIGGER" in e["note"] or "Trigger" in e["note"] for e in entries)
    days = client.get("/api/history").json()
    assert len(client.get(f"/api/day/{days[0]['day']}").json()) >= 1
    csv_text = client.get("/api/export.csv").text
    assert csv_text.startswith("vehicle,device,epoch,seq,taken_at,i0,i,flags,k,valid")
    assert len(csv_text.strip().splitlines()) == 62


def test_only_the_vehicle_name_is_changeable_and_limit_is_fixed():
    ok = client.post("/api/settings", json={"name": "Truck", "limit_k": 9.9, "path_len_m": 5})
    v = ok.json()["vehicle"]
    assert v["name"] == "Truck" and v["limit_k"] == 2.45 and v["path_len_m"] == 0.10


def test_onboarding_survives_demo_scenarios_but_not_delete_all():
    assert client.post("/api/onboarding", json={"name": "Swift"}).json()["onboarded"] is True
    assert client.post("/api/scenario", json={"name": "steady_healthy"}).json()["onboarded"] is True
    s = client.delete("/api/data").json()
    assert s["reading_count"] == 0 and s["onboarded"] is False
    assert client.get("/").status_code == 200


def test_vehicle_kind_is_just_an_icon():
    client.delete("/api/data")
    s = client.post("/api/onboarding", json={"name": "Tipper", "kind": "truck"}).json()
    assert s["vehicle"]["kind"] == "truck" and s["vehicle"]["limit_k"] == 2.45
    s = client.post("/api/vehicles", json={"name": "Rickshaw", "kind": "auto"}).json()
    assert [v["kind"] for v in s["vehicles"]] == ["truck", "auto"]
    s = client.post("/api/settings", json={"name": "Rickshaw", "kind": "spaceship"}).json()
    assert s["vehicle"]["kind"] == "auto"          # unknown kinds are ignored
    assert client.post("/api/vehicles", json={"name": "Plain"}).json()["vehicle"]["kind"] == "car"
    client.delete("/api/data")


def test_vehicles_through_the_api():
    client.delete("/api/data")
    client.post("/api/onboarding", json={"name": "Swift"})
    client.post("/api/scenario", json={"name": "steady_healthy"})
    first = client.get("/api/state").json()["vehicle"]["id"]
    assert client.get("/api/state").json()["scenario"] == "steady_healthy"
    s = client.post("/api/vehicles", json={"name": "Dzire"}).json()
    assert s["vehicle"]["name"] == "Dzire" and s["reading_count"] == 0
    assert s["scenario"] is None                      # the sample belongs to the first vehicle only
    assert [v["name"] for v in s["vehicles"]] == ["Swift", "Dzire"]
    second = s["vehicle"]["id"]
    assert client.post("/api/measure", json={"vehicle_id": second}).status_code == 409   # no meter on it yet
    s = client.post("/api/pair", json={"id": "SOOT-SIM-02", "vehicle_id": second}).json()
    s = client.post("/api/measure", json={"vehicle_id": second}).json()
    assert s["reading_count"] == 1 and s["vehicle"]["id"] == second
    assert {v["id"]: v["meter"] for v in s["vehicles"]} == {first: "SootAble-7F2A", second: "SootAble-3C91"}
    s = client.post("/api/vehicles/select", json={"id": first}).json()
    assert s["reading_count"] == 60 and len(client.get("/api/history").json()) == 60
    assert client.post("/api/measure", json={"vehicle_id": 999}).status_code == 404
    assert client.post("/api/vehicles/select", json={"id": 999}).status_code == 404
    csv_rows = client.get("/api/export.csv").text.strip().splitlines()
    assert len(csv_rows) == 1 + 61 and any(r.startswith("Dzire,") for r in csv_rows)
    s = client.delete(f"/api/vehicles/{second}").json()
    assert [v["name"] for v in s["vehicles"]] == ["Swift"]
    assert client.delete(f"/api/vehicles/{first}").status_code == 400


def test_readings_report_plain_language_reasons():
    client.post("/api/scenario", json={"name": "no_reference"})
    days = client.get("/api/history").json()
    reasons = {d["reason"] for d in days if d["reason"]}
    assert reasons == {"The device couldn't take a clean-air reference."}
    assert client.get("/api/state").json()["latest"]["time"]


def test_installable_app_files_are_served():
    import json
    man = client.get("/manifest.webmanifest")
    assert man.status_code == 200 and man.headers["content-type"].startswith("application/manifest+json")
    icons = json.loads(man.text)["icons"]
    assert any(i["purpose"] == "maskable" for i in icons)
    for i in icons:
        assert client.get(i["src"]).status_code == 200
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    assert sw.headers["cache-control"] == "no-cache"
    assert client.get("/static/apple-touch-icon.png").status_code == 200
    assert client.get("/static/favicon.png").status_code == 200
    assert client.get("/static/logo-mark.png").status_code == 200
    hw = client.get("/hardware/", follow_redirects=True)
    assert hw.status_code == 200 and "three" in hw.text
    assert client.get("/hardware/three.min.js").status_code == 200


def test_sync_with_nothing_new_changes_no_readings():
    client.post("/api/scenario", json={"name": "steady_healthy"})
    before = client.get("/api/state").json()["reading_count"]
    after = client.post("/api/sync").json()["reading_count"]
    assert after == before == client.get("/api/state").json()["reading_count"]
