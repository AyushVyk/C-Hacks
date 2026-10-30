"""FastAPI server: a small JSON API plus the static dashboard."""
import csv
import io
import os
import threading
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, engine, scenarios
from .app import SootableApp
from .store import Store

ROOT = os.path.dirname(os.path.dirname(__file__))
STATIC = os.path.join(ROOT, "web")
HARDWARE = os.path.join(ROOT, "hardware")
DB_PATH = os.environ.get("SOOTABLE_DB", os.path.join(os.path.dirname(__file__), "..", "data", "sootable.db"))

state = SootableApp(Store(DB_PATH))
lock = threading.Lock()  # one request at a time keeps the simulated link simple
api = FastAPI(title="SootAble")
app = api


class Settings(BaseModel):
    name: str
    kind: str | None = None         # car, suv, truck or auto (only changes the icon)


class Level(BaseModel):
    k: float
    flags: int = 0


class Scenario(BaseModel):
    name: str
    vehicle_id: int | None = None   # with keep: the vehicle to fill (defaults to the one being viewed)
    keep: bool = False              # fill only that vehicle and leave every other one alone


class Measure(BaseModel):
    vehicle_id: int | None = None   # defaults to the vehicle being viewed


class VehicleRef(BaseModel):
    id: int


class DeviceRef(BaseModel):
    id: str
    vehicle_id: int | None = None   # the vehicle to pair the meter to; defaults to the one being viewed


def clean_name(name: str) -> str:
    return name.strip()[:40] or "My vehicle"


def known_vehicle(vid):
    if vid is not None and vid not in [v["id"] for v in state.store.vehicles()]:
        raise HTTPException(404, "unknown vehicle")


def snapshot(extra=None) -> dict:
    out = engine.summary(state.store, state.clock())
    meter = state.store.device_for_vehicle(out["vehicle"]["id"])   # the meter on the vehicle being viewed
    chamber = state.store.get_setting(f"chamber_mm:{meter['id']}") if meter else None
    out["device"] = {"paired": bool(meter), "id": meter["id"] if meter else None,
                     "name": meter["name"] if meter else None,
                     "epoch": meter["last_epoch"] if meter else None, "fw": meter["fw"] if meter else None,
                     "chamber_mm": int(chamber) if chamber else None,
                     "last_sync": engine.iso_local(meter["last_seen_at"]) if meter and meter["last_seen_at"] else None,
                     "sim_k": state.device.current_k, "sim_flags": state.device.current_flags}
    out["meters_paired"] = len(state.store.devices())
    out["vehicles"] = engine.vehicle_cards(state.store, state.clock())
    # "demo data" only applies to a vehicle that a demo scenario filled
    out["scenario"] = state.demo.get(out["vehicle"]["id"])
    out["alert_count"] = len(state.store.alerts(out["vehicle"]["id"]))
    out["storage_bytes"] = state.store.size_bytes()
    out.update(extra or {})
    return out


@api.get("/api/state")
def get_state():
    with lock:
        return snapshot()


@api.get("/api/scenarios")
def get_scenarios():
    return scenarios.NAMES


@api.post("/api/scenario")
def run_scenario(body: Scenario):
    if body.name not in scenarios.NAMES:
        raise HTTPException(404, "unknown scenario")
    known_vehicle(body.vehicle_id)
    with lock:
        try:
            info = scenarios.run(state, body.name, body.vehicle_id, body.keep)
        except LookupError:
            raise HTTPException(409, "Every demo meter is already in use")
        return snapshot({"new_alerts": info["sync"]["alerts"] + info.get("first_sync", {}).get("alerts", [])})


@api.get("/api/scan")
def scan():
    """Look for meters in range (what a Bluetooth scan for the SootAble service returns)."""
    with lock:
        return {"devices": state.scan()}


@api.post("/api/pair")
def pair(body: DeviceRef):
    """Connect a meter from the scan to a vehicle. A meter that was on another vehicle is moved."""
    known_vehicle(body.vehicle_id)
    with lock:
        try:
            result = state.pair(body.id, body.vehicle_id)
        except LookupError:
            raise HTTPException(404, "that meter is no longer in range")
        return snapshot({"new_alerts": result["alerts"], "complete": result["complete"]})


@api.delete("/api/meters/{device_id}")
def forget_meter(device_id: str):
    with lock:
        state.forget_meter(device_id)
        return snapshot()


@api.post("/api/sync")
def sync():
    """Sync every paired meter."""
    if not state.is_paired():
        raise HTTPException(409, "Pair a meter first")
    with lock:
        result = state.sync()
        return snapshot({"new_alerts": result["alerts"], "complete": result["complete"]})


@api.post("/api/measure")
def measure(body: Measure | None = None):
    """Take a reading with the vehicle's own meter."""
    vid = body.vehicle_id if body else None
    known_vehicle(vid)
    with lock:
        try:
            result = state.measure(vid)
        except LookupError:
            raise HTTPException(409, "No meter is connected to this vehicle")
        return snapshot({"new_alerts": result["alerts"], "complete": result["complete"]})


@api.post("/api/vehicles")
def add_vehicle(body: Settings):
    """Add a vehicle and switch to it."""
    with lock:
        state.store.set_active_vehicle(state.store.add_vehicle(clean_name(body.name), body.kind or "car"))
        return snapshot()


@api.post("/api/vehicles/select")
def select_vehicle(body: VehicleRef):
    if body.id not in [v["id"] for v in state.store.vehicles()]:
        raise HTTPException(404, "unknown vehicle")
    with lock:
        state.store.set_active_vehicle(body.id)
        return snapshot()


@api.delete("/api/vehicles/{vid}")
def remove_vehicle(vid: int):
    with lock:
        if not state.store.delete_vehicle(vid):
            raise HTTPException(400, "you need at least one vehicle")
        return snapshot()


@api.post("/api/sim/level")
def set_level(body: Level):
    """Choose the smoke level (and optional fault flags) the next measurement will report, on every demo meter."""
    with lock:
        for meter in state.meters.values():
            meter.device.current_k = body.k
            meter.device.current_flags = body.flags
        return snapshot()


@api.get("/api/inspector")
def inspector(since: int = 0):
    return {"entries": state.inspector.since(since), "last": state.inspector.counter}


@api.get("/api/trend")
def get_trend(days: int = 30):
    with lock:
        return engine.trend(state.store, state.clock(), max(7, min(days, config.RETENTION_DAYS)))


@api.get("/api/history")
def history():
    return engine.history(state.store)


@api.get("/api/day/{day}")
def day(day: str):
    return engine.day_detail(state.store, day)


@api.get("/api/alerts")
def alerts():
    return state.store.alerts(state.store.active_vehicle_id())


@api.post("/api/settings")
def save_settings(body: Settings):
    """The only thing an owner can change about a vehicle is its name."""
    with lock:
        state.store.rename_vehicle(clean_name(body.name), kind=body.kind)
        return snapshot()


@api.post("/api/onboarding")
def finish_onboarding(body: Settings):
    with lock:
        state.store.rename_vehicle(clean_name(body.name), kind=body.kind)
        state.store.set_setting("onboarded", "1")
        return snapshot()


@api.post("/api/baseline/reset")
def reset_baseline():
    with lock:
        vid = state.store.active_vehicle_id()
        state.store.vset(vid, "baseline_from", datetime.fromtimestamp(state.clock()).date().isoformat())
        state.store.vdel(vid, "baseline_k")
        return snapshot()


@api.post("/api/chamber/cleaned")
def chamber_cleaned():
    """The sensor window is on the meter, so cleaning it resets the reminder for every vehicle."""
    with lock:
        for v in state.store.vehicles():
            state.store.vset(v["id"], "readings_at_clean", len(state.store.readings(v["id"])))
        return snapshot()


@api.delete("/api/data")
def delete_data():
    with lock:
        state.reset(wipe=True)
        return snapshot()


@api.get("/api/export.csv")
def export_csv():
    """Every reading for every vehicle, one row each."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["vehicle", "device", "epoch", "seq", "taken_at", "i0", "i", "flags", "k", "valid"])
    for v in state.store.vehicles():
        for r in state.store.readings(v["id"]):
            writer.writerow([v["name"], r["device_id"], r["epoch"], r["seq"], engine.iso_local(r["taken_at"]),
                             r["i0"], r["i"], r["flags"], "" if r["k"] is None else round(r["k"], 4), r["valid"]])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=sootable-readings.csv"})


@api.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@api.get("/manifest.webmanifest")
def manifest():
    return FileResponse(os.path.join(STATIC, "manifest.webmanifest"), media_type="application/manifest+json")


@api.get("/sw.js")
def service_worker():
    """Served from the root so its scope covers the whole app. Never cached, so updates arrive at once."""
    return FileResponse(os.path.join(STATIC, "sw.js"), media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


api.mount("/static", StaticFiles(directory=STATIC), name="static")
# The 3D simulator of the meter (the CAD model); /hardware/ serves its index.html.
api.mount("/hardware", StaticFiles(directory=HARDWARE, html=True), name="hardware")
