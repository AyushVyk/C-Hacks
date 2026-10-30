"""Status and alert rules (spec section 5.5). Plain rules, no ML."""
from . import config

OK, WATCH, OVER = "OK", "WATCH", "OVER"


def status(smoothed_k, limit: float):
    if smoothed_k is None:
        return None
    if round(smoothed_k, 2) > limit:  # strictly above, compared after rounding
        return OVER
    if round(smoothed_k, 2) >= round(config.WATCH_FRACTION * limit, 2):  # avoid float noise
        return WATCH
    return OK


_RANK = {None: 0, OK: 0, WATCH: 1, OVER: 2}


def settle(latched, raw, smoothed_k, limit: float):
    """Status used for alerts: goes up at once, comes down only once clearly below its threshold.

    Without this, a value hovering at the limit would flip OVER/WATCH every few days and re-alert.
    The status shown on the Home screen is the raw one, exactly as the spec defines it.
    """
    if _RANK[raw] >= _RANK[latched] or smoothed_k is None:
        return raw
    threshold = limit if latched == OVER else config.WATCH_FRACTION * limit
    return latched if smoothed_k >= config.HYSTERESIS * threshold else raw


def rise_detected(smoothed_k, baseline_k, recent_daily: list) -> bool:
    """recent_daily: daily values, oldest first.

    Interpretation of "risen on at least 3 of the last 5 daily values": of the
    last 5 day-to-day steps, at least 3 went up.
    """
    if smoothed_k is None or baseline_k is None:
        return False
    if smoothed_k < config.RISE_FACTOR * baseline_k:
        return False
    last = recent_daily[-(5 + 1):]
    ups = sum(1 for a, b in zip(last, last[1:]) if b > a)
    return ups >= config.RISE_STEPS_NEEDED


def new_alerts(prev_status, new_status, rise_now, rise_before, last_sent: dict, now: int):
    """Decide which alerts fire. Returns [(type, notify)].

    An alert is logged whenever the status changes; notify is False when the
    same type was already notified in the last 7 days.
    """
    events = []
    if new_status == WATCH and prev_status in (None, OK):
        events.append("WATCH")
    if new_status == OVER and prev_status != OVER:
        events.append("OVER")
    if rise_now and not rise_before:
        events.append("RISE")
    out = []
    for t in events:
        recent = t in last_sent and now - last_sent[t] < config.ALERT_COOLDOWN_S
        out.append((t, not recent))
    return out


NEXT_STEP = {
    "WATCH": "A service check would be wise before it gets worse.",
    "RISE": "Smoke is climbing quickly. Consider an injector and air filter check.",
    "OVER": "Consider an injector and air filter check, then get a PUC test.",
}


def message(alert_type: str, k: float, limit: float) -> str:
    """States the number and the limit, then one suggested next step."""
    return f"Smoke level is {k:.2f} against a limit of {limit:g}. {NEXT_STEP[alert_type]}"


def home_note(today_k, current_status, limit: float):
    """Neutral line for a single high reading that has not changed the status."""
    if today_k is not None and round(today_k, 2) > limit and current_status != OVER:
        return "One high reading today, check again tomorrow."
    return None
