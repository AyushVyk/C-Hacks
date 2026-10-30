"""Wires the store, the simulated meters and the phone sessions together."""
import time

from . import engine
from .device_sim import DEVICE_ID, FLEET, VirtualDevice
from .link import Inspector, SimTransport
from .session import PhoneSession


class Clock:
    """Real time plus an offset, so a scenario can replay an earlier sync."""

    def __init__(self):
        self.offset = 0.0

    def __call__(self) -> float:
        return time.time() + self.offset


class Meter:
    """One meter in range: the virtual device, the link to it, and the phone's session with it."""

    def __init__(self, device, transport, session):
        self.device, self.transport, self.session = device, transport, session


class SootableApp:
    def __init__(self, store):
        self.store = store
        self.clock = Clock()
        self.inspector = Inspector()
        self.demo = {}                 # vehicle id -> the demo scenario that filled it
        self._build_fleet()

    # ---------- the meters in range ----------
    def _build_fleet(self):
        self.meters = {}
        for i, (device_id, name) in enumerate(FLEET):
            self._add_meter(VirtualDevice(self.clock, seed=1 + 7 * i, device_id=device_id, name=name))

    def _add_meter(self, device, **link_options):
        transport = SimTransport(device, self.inspector, **link_options)
        session = PhoneSession(self.store, device.device_id, self.clock, self.inspector)
        transport.on_bytes = session.on_bytes
        session.write = transport.write
        self.meters[device.device_id] = Meter(device, transport, session)

    def attach(self, device, **link_options):
        """Replace the demo meter (the first in the fleet), which sample data and the developer tools drive."""
        self._add_meter(device, **link_options)

    # the demo meter, for scenarios, developer tools and tests
    @property
    def device(self):
        return self.meters[DEVICE_ID].device

    @property
    def transport(self):
        return self.meters[DEVICE_ID].transport

    @property
    def session(self):
        return self.meters[DEVICE_ID].session

    def reset(self, wipe: bool = False):
        """Forget all readings and alerts and start with fresh meters.

        The vehicles and the first-run flag are kept, unless wipe is set (delete all my data).
        """
        if wipe:
            self.store.wipe_everything()
        else:
            self.store.clear_readings_and_alerts()
        self.clock.offset = 0.0
        self.inspector = Inspector()
        self.demo = {}
        self._build_fleet()

    # ---------- pairing: a meter belongs to one vehicle, and a vehicle has one meter ----------
    def meter_for(self, vehicle_id):
        """The id of the meter paired to a vehicle, or None."""
        row = self.store.device_for_vehicle(vehicle_id)
        return row["id"] if row else None

    def is_paired(self, vehicle_id=None) -> bool:
        """Does this vehicle have a meter (or, with no vehicle given, is any meter paired)?"""
        return bool(self.meter_for(vehicle_id)) if vehicle_id else bool(self.store.devices())

    def scan(self) -> list:
        """Meters in range, each marked with the vehicle it is paired to (if any)."""
        vehicles = {v["id"]: v["name"] for v in self.store.vehicles()}
        found = []
        for meter in self.meters.values():
            adv = dict(meter.transport.scan()[0])
            row = self.store.device(adv["id"])
            paired = bool(row and row["paired"] and row["vehicle_id"] in vehicles)
            adv["vehicle_id"] = row["vehicle_id"] if paired else None
            adv["vehicle"] = vehicles[row["vehicle_id"]] if paired else None
            found.append(adv)
        return found

    def pair(self, device_id: str, vehicle_id=None) -> dict:
        """Connect a meter from the scan to a vehicle: the handshake runs and anything the meter stored is pulled in.

        A vehicle has one meter, so pairing replaces any other meter on it. A meter that was on another
        vehicle is synced first (its waiting readings belong there) and then moved.
        """
        meter = self.meters.get(device_id)
        if meter is None:
            raise LookupError(device_id)
        vid = vehicle_id or self.store.active_vehicle_id()
        name = meter.transport.scan()[0]["name"]
        row = self.store.device(device_id)
        if row and row["paired"] and row["vehicle_id"] != vid:
            self.sync_meter(device_id)
        other = self.meter_for(vid)
        if other and other != device_id:
            self.forget_meter(other)
        self.store.link_device(device_id, vid)
        result = self.sync_meter(device_id)
        self.store.set_device_name(device_id, name)
        self.store.set_paired(device_id, True)
        self.store.set_active_vehicle(vid)
        return result

    def free_meter_id(self):
        """A demo meter that is not paired to any vehicle, or None if they are all in use."""
        used = {d["id"] for d in self.store.devices()}
        return next((device_id for device_id, _ in FLEET if device_id not in used), None)

    def pair_demo_meter(self, vehicle_id=None, device_id=DEVICE_ID):
        """Sample data: a demo meter counts as paired to the vehicle it filled."""
        vid = vehicle_id or self.store.active_vehicle_id()
        other = self.meter_for(vid)
        if other and other != device_id:
            self.forget_meter(other)
        self.store.link_device(device_id, vid)
        self.store.set_device_name(device_id, self.meters[device_id].device.name)
        self.store.set_paired(device_id, True)

    def forget_meter(self, device_id: str):
        self.store.forget_device(device_id)
        if device_id in self.meters:
            self.meters[device_id].session.reset()

    # ---------- syncing and measuring ----------
    def sync_meter(self, device_id: str, tries: int = 30) -> dict:
        """Connect to one meter and pull its new readings, reconnecting until everything arrived."""
        meter = self.meters[device_id]
        for _ in range(tries):
            meter.session.reset()
            try:
                meter.transport.connect()
            except ConnectionError:
                pass
            if meter.session.complete:
                break
        return self._result(meter.session.complete)

    def sync(self, tries: int = 30) -> dict:
        """Sync every paired meter. Each reading goes to the vehicle its meter is paired to."""
        alerts, complete = [], True
        for row in self.store.devices():
            if row["id"] in self.meters:
                r = self.sync_meter(row["id"], tries)
                alerts += r["alerts"]
                complete = complete and r["complete"]
        return {"complete": complete, "alerts": alerts}

    def measure(self, vehicle_id=None) -> dict:
        """Take a reading with the vehicle's own meter: sync it first, then send TRIGGER."""
        vid = vehicle_id or self.store.active_vehicle_id()
        device_id = self.meter_for(vid)
        if device_id is None:
            raise LookupError("no meter is paired to this vehicle")
        self.sync_meter(device_id)
        self.store.set_active_vehicle(vid)
        meter = self.meters[device_id]
        try:
            meter.session.begin_trigger()
        except ConnectionError:
            pass
        return self._result(meter.session.complete)

    def _result(self, complete: bool) -> dict:
        for v in self.store.vehicles():      # before pruning, which removes the oldest readings
            engine.ensure_baseline(self.store, v["id"])
        self.store.prune(self.clock())
        new = engine.refresh_alerts(self.store)
        return {"complete": complete, "alerts": new}
