"""Turns stored readings into what the screens show: daily values, status, alerts.

Every function works on one vehicle. Leave `vid` out to use the vehicle currently being viewed.
"""
from datetime import date, datetime, timedelta
from statistics import mean

from . import alerts, config, daily
from .frame import FAN_FAULT, LOW_BATT, MANUAL, NO_REF, SATURATED

FLAG_NAMES = [(NO_REF, "NO_REF"), (SATURATED, "SATURATED"), (LOW_BATT, "LOW_BATT"),
              (FAN_FAULT, "FAN_FAULT"), (MANUAL, "MANUAL")]

FRIENDLY = {
    "No clean-air reference was taken": "The device couldn't take a clean-air reference.",
    "Sensor saturated": "Too much light reached the sensor.",
    "Fan fault": "The fan didn't start properly.",
}


def friendly(reason):
    """Plain-language version of why a reading was not used."""
    return FRIENDLY.get(reason, "The reading looked unreliable.") if reason else None


def flag_names(flags: int) -> list:
    return [name for bit, name in FLAG_NAMES if flags & bit]


def iso_local(ts: int) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _vid(store, vid):
    return vid or store.active_vehicle_id()


def daily_k(store, vid=None) -> dict:
    """{day: median k of the valid readings that day}. Days without a valid reading are absent."""
    rows = [(r["taken_at"], r["k"], bool(r["valid"])) for r in store.readings(_vid(store, vid))]
    return {d: k for d, (k, _n) in daily.daily_values(rows).items()}


def baseline_of(store, dk: dict, vid=None):
    """The saved baseline, or one computed from the readings if it is not saved yet."""
    vid = _vid(store, vid)
    saved = store.vget(vid, "baseline_k")
    if saved is not None:
        return float(saved)
    start = store.vget(vid, "baseline_from", "0000-00-00")
    return daily.baseline({d: k for d, k in dk.items() if d >= start})


def ensure_baseline(store, vid=None):
    """Save the baseline as soon as it exists. It is built from the oldest readings, which
    are deleted after the retention period, so it must be kept on its own."""
    vid = _vid(store, vid)
    if store.vget(vid, "baseline_k") is None:
        base = baseline_of(store, daily_k(store, vid), vid)
        if base is not None:
            store.vset(vid, "baseline_k", base)


def alert_history(store, dk: dict, limit: float, vid=None) -> list:
    """Replay the days in order and return every alert that would have fired."""
    vid = _vid(store, vid)
    days = sorted(dk)
    start = store.vget(vid, "baseline_from", "0000-00-00")
    saved = store.vget(vid, "baseline_k")
    first = daily.baseline({d: dk[d] for d in [x for x in days if x >= start][:config.BASELINE_DAYS]})
    base_value = float(saved) if saved is not None else first
    out, prev, rise_before, last_sent, since_count = [], None, False, {}, 0
    for n, day in enumerate(days):
        s = daily.smoothed(dk, date.fromisoformat(day))  # only looks back from `day`
        st = alerts.settle(prev, alerts.status(s, limit), s, limit)
        since_count += day >= start
        # the baseline only applies once 14 days exist, as when it was first measured
        base = base_value if since_count >= config.BASELINE_DAYS else None
        rise = alerts.rise_detected(s, base, [dk[d] for d in days[max(0, n - 5):n + 1]])
        # latch with hysteresis: once RISE has fired it stays on until the average falls well back,
        # so noise around the threshold on a slow climb cannot trigger it again and again
        still_high = s is not None and base is not None and s >= config.RISE_RELEASE_FACTOR * base
        rise = rise or (rise_before and still_high)
        now = int(datetime.fromisoformat(day).timestamp())
        for kind, notify in alerts.new_alerts(prev, st, rise, rise_before, last_sent, now):
            out.append({"created_at": now, "day": day, "type": kind, "k_smooth": s, "notify": notify,
                        "message": alerts.message(kind, s, limit)})
            if notify:
                last_sent[kind] = now
        prev = st or prev
        rise_before = rise
    return out


def refresh_alerts(store, vid=None) -> list:
    """Save alerts that are new since the last run, for one vehicle or (by default) every vehicle.

    Returns the ones to notify about, each tagged with its vehicle.
    """
    new = []
    for v in ([store.vehicle(vid)] if vid else store.vehicles()):
        for a in alert_history(store, daily_k(store, v["id"]), v["limit_k"], v["id"]):
            if store.add_alert(a["created_at"], a["day"], a["type"], a["k_smooth"], a["message"], a["notify"],
                               v["id"]) and a["notify"]:
                new.append({**a, "vehicle_id": v["id"], "vehicle": v["name"]})
    return new


def trend(store, now: float, days: int, vid=None) -> dict:
    """Daily values and the rolling average for the last `days` days, plus a text description.

    Longer ranges start at the first reading, so a half-empty history is not stretched.
    """
    vid = _vid(store, vid)
    limit = store.vehicle(vid)["limit_k"]
    dk = daily_k(store, vid)
    today = datetime.fromtimestamp(now).date()
    points = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        points.append({"day": day.isoformat(), "k": dk.get(day.isoformat()), "avg": daily.smoothed(dk, day)})
    if days > 30:
        while points and points[0]["k"] is None:
            points.pop(0)
    values = [p["k"] for p in points if p["k"] is not None]
    text = (f"Last {len(points)} days: average {mean(values):.2f}, highest {max(values):.2f}, "
            f"limit {limit:g}." if values else f"No readings in the last {days} days.")
    return {"days": points, "text": text}


def streak(dk: dict, today: date) -> int:
    """Consecutive days with a usable reading, ending today (or yesterday if today is not done yet)."""
    day = today if today.isoformat() in dk else today - timedelta(days=1)
    count = 0
    while day.isoformat() in dk:
        count += 1
        day -= timedelta(days=1)
    return count


def forecast(dk: dict, limit: float, today: date):
    """A straight-line estimate of when the smoke level reaches the legal limit.

    Plain arithmetic on the last 60 days (least-squares line), shown for information only. It never
    triggers an alert. Returns None unless there is a clear upward trend and the limit is still ahead.
    """
    start = (today - timedelta(days=59)).isoformat()
    points = sorted((date.fromisoformat(d).toordinal(), k) for d, k in dk.items() if start <= d <= today.isoformat())
    if len(points) < config.FORECAST_MIN_POINTS:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    xbar, ybar = mean(xs), mean(ys)
    sxx = sum((x - xbar) ** 2 for x in xs)
    slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / sxx
    now_fit = ybar + slope * (today.toordinal() - xbar)
    if slope < config.FORECAST_MIN_SLOPE or now_fit >= limit:
        return None
    days = (limit - now_fit) / slope
    if days > config.FORECAST_MAX_DAYS:
        return None
    return {"days": round(days), "date": (today + timedelta(days=round(days))).isoformat(),
            "per_month": round(slope * 30, 2)}


def vehicle_cards(store, now: float) -> list:
    """One line per vehicle for the switcher: current status, last reading and its meter."""
    today = datetime.fromtimestamp(now).date()
    cards = []
    for v in store.vehicles():
        dk = daily_k(store, v["id"])
        smooth = daily.smoothed(dk, today)
        rows = store.readings(v["id"])
        meter = store.device_for_vehicle(v["id"])
        cards.append({"id": v["id"], "name": v["name"], "kind": v["kind"], "smoothed": smooth,
                      "status": alerts.status(smooth, v["limit_k"]), "reading_count": len(rows),
                      "last_reading": iso_local(rows[-1]["taken_at"]) if rows else None,
                      "meter": meter["name"] if meter else None})
    return cards


def summary(store, now: float, vid=None) -> dict:
    vid = _vid(store, vid)
    vehicle = store.vehicle(vid)
    limit = vehicle["limit_k"]
    dk = daily_k(store, vid)
    today = datetime.fromtimestamp(now).date()
    smooth = daily.smoothed(dk, today)
    st = alerts.status(smooth, limit)

    chart = trend(store, now, 30, vid)

    rows = store.readings(vid)
    total = len(rows)
    since_clean = total - int(store.vget(vid, "readings_at_clean", 0))
    latest = rows[-1] if rows else None
    device_latest = store.readings()[-1:]  # battery and fan are about the meter, not one vehicle
    return {
        "onboarded": store.get_setting("onboarded") == "1",
        "daily_count": len(dk),
        "today_done": today.isoformat() in dk,
        "streak": streak(dk, today),
        "forecast": forecast(dk, limit, today),
        "latest": ({"time": iso_local(latest["taken_at"]), "k": latest["k"], "valid": bool(latest["valid"]),
                    "reason": friendly(latest["reason"])} if latest else None),
        "vehicle": vehicle,
        "smoothed": smooth,
        "status": st,
        "note": alerts.home_note(dk.get(today.isoformat()), st, limit),
        "last_reading": iso_local(latest["taken_at"]) if latest else None,
        "chart": chart["days"],
        "chart_text": chart["text"],
        "retention_days": config.RETENTION_DAYS,
        "baseline": baseline_of(store, dk, vid),
        "clean_reminder": since_clean >= config.CLEAN_REMINDER_READINGS,
        "reading_count": total,
        "low_battery": any(r["flags"] & LOW_BATT for r in device_latest),
        "fault": any(r["flags"] & FAN_FAULT for r in device_latest),
    }


def history(store, vid=None) -> list:
    vid = _vid(store, vid)
    days = {}
    for r in store.readings(vid):
        days.setdefault(daily.local_day(r["taken_at"]), []).append(r)
    dk = daily_k(store, vid)
    return [{"day": d, "k": dk.get(d), "count": len(rs), "time": iso_local(rs[0]["taken_at"]),
             "reason": friendly(next((r["reason"] for r in rs if not r["valid"]), None))}
            for d, rs in sorted(days.items(), reverse=True)]


def day_detail(store, day: str, vid=None) -> list:
    return [{"seq": r["seq"], "epoch": r["epoch"], "time": iso_local(r["taken_at"]), "i0": r["i0"],
             "i": r["i"], "flags": flag_names(r["flags"]), "k": r["k"], "valid": bool(r["valid"]),
             "reason": friendly(r["reason"])}
            for r in store.readings(_vid(store, vid)) if daily.local_day(r["taken_at"]) == day]
