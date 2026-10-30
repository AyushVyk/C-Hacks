"""Scripted demo scenarios (spec section 10). Each one fills the virtual device and syncs."""
import math
import random
import time

from .app import DEVICE_ID
from .device_sim import L_MM, VirtualDevice
from .frame import NO_REF, SATURATED
from .k import evaluate_reading

DAY = 86400
NAMES = {
    "steady_healthy": "Healthy engine, 60 days around k = 1.4",
    "slow_rise": "Slow rise from 1.4 to 2.7 (WATCH, RISE, then OVER)",
    "sudden_spike": "One bad reading today (no alarm)",
    "noisy": "Noisy readings, smoothed by the rolling average",
    "split_frames": "Frames split and merged on the link",
    "crc_corruption": "Random bit errors on the link",
    "drop_mid_sync": "Link lost part way through a sync",
    "epoch_change": "Device reboots between two syncs",
    "no_reference": "Some readings with no clean-air reference",
    "saturation": "Some readings with a saturated sensor",
    "long_term": "1000 days of slow engine wear (about 3 years)",
    "wearing_out": "Engine wearing out: still legal, heading for the limit",
}


def _fill(device, ks, flags=None, end=None):
    """Store one reading per day, the last one two minutes before `end`."""
    end = end or time.time()
    for j, k in enumerate(ks):
        taken = end - (len(ks) - 1 - j) * DAY - 120
        device.record(k, taken, (flags or {}).get(j, 0))


def _healthy(rng, n=60, mean=1.4, sd=0.05):
    return [max(0.05, rng.gauss(mean, sd)) for _ in range(n)]


def run(app, name: str, vehicle_id=None, keep: bool = False) -> dict:
    """Play a scenario and return what happened.

    By default the whole app is reset first (first-run demo data, developer tools). With keep=True only
    one vehicle is filled: its own data is replaced, every other vehicle is left alone, and a demo meter
    that no vehicle is using becomes its meter. Raises LookupError if every demo meter is already in use.
    """
    if keep:
        vid = vehicle_id or app.store.active_vehicle_id()
        old = app.meter_for(vid)
        if old:
            app.forget_meter(old)
        device_id = app.free_meter_id()
        if device_id is None:
            raise LookupError("every demo meter is already in use")
        app.store.clear_vehicle_data(vid)
        app.store.set_active_vehicle(vid)
    else:
        app.reset()
        vid, device_id = app.store.active_vehicle_id(), DEVICE_ID
    app.demo[vid] = name
    rng = random.Random(7)
    device = VirtualDevice(app.clock, seed=11, device_id=device_id, name=app.meters[device_id].device.name)
    link = {}
    info = {}

    if name == "steady_healthy":
        _fill(device, _healthy(rng))
    elif name == "slow_rise":
        _fill(device, [1.4 + 1.3 * j / 59 + rng.gauss(0, 0.02) for j in range(60)])
    elif name == "sudden_spike":
        _fill(device, _healthy(rng, 59) + [3.5])
    elif name == "noisy":
        _fill(device, _healthy(rng, sd=0.4))
    elif name == "split_frames":
        _fill(device, _healthy(rng))
        link = {"chunk": "random"}
    elif name == "crc_corruption":
        _fill(device, _healthy(rng))
        link = {"corrupt_rate": 0.05}
    elif name == "drop_mid_sync":
        _fill(device, _healthy(rng))
        link = {"drop_after_bytes": 300}
    elif name == "epoch_change":
        return _epoch_change(app, device, rng, vid)
    elif name == "no_reference":
        _fill(device, _healthy(rng), {j: NO_REF for j in (10, 11, 30, 45)})
    elif name == "saturation":
        _fill(device, _healthy(rng), {j: SATURATED for j in (12, 33, 50)})
    elif name == "long_term":
        _long_term(app, device, rng, vid)
    elif name == "wearing_out":
        _fill(device, [1.2 + 0.95 * j / 119 + rng.gauss(0, 0.03) for j in range(120)])
    else:
        raise ValueError(f"unknown scenario {name}")

    app.attach(device, **link)
    app.pair_demo_meter(vid, device_id)   # the demo meter counts as paired to the vehicle being filled
    if name == "drop_mid_sync":
        info["first_sync"] = app.sync_meter(device_id, tries=1)
    info["sync"] = app.sync_meter(device_id)
    _sensor_is_clean(app, vid)
    return info


def _sensor_is_clean(app, vid):
    """Sample history counts as readings taken on a clean sensor, so the cleaning reminder starts from zero."""
    app.store.vset(vid, "readings_at_clean", len(app.store.readings(vid)))


def _long_term(app, device, rng, vid, days=1000, live=3):
    """Slow wear from k = 1.0 to 2.6. A real device is synced daily, so the older days are
    stored as if earlier syncs had already happened and only the last few arrive live."""
    now = time.time()
    ks = [1.0 + 1.6 * j / (days - 1) + rng.gauss(0, 0.04) for j in range(days)]
    old = days - live
    for j in range(old):
        taken = now - (days - 1 - j) * DAY - 120
        i0 = 920
        i = round(i0 * math.exp(-ks[j] * L_MM / 1000))
        k, valid = evaluate_reading(i0, i, 0, L_MM / 1000)
        app.store.save_reading(device.device_id, 1, j, taken, taken, i0, i, 0, k, valid, None, vid)
    app.store.set_acked(device.device_id, 1, old - 1)  # commits
    device.next_seq = old
    _fill(device, ks[old:])


def _epoch_change(app, device, rng, vid):
    """30 days synced a month ago, then a reboot, then 30 newer days with seq restarting at 0."""
    now = time.time()
    app.attach(device)
    app.pair_demo_meter(vid, device.device_id)
    app.clock.offset = -30 * DAY
    _fill(device, _healthy(rng, 30), end=now - 30 * DAY)
    first = app.sync_meter(device.device_id)
    device.reboot()
    app.clock.offset = 0.0
    _fill(device, _healthy(rng, 30), end=now)
    info = {"first_sync": first, "sync": app.sync_meter(device.device_id)}
    _sensor_is_clean(app, vid)
    return info
