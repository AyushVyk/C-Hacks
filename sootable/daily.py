"""Daily values, smoothed trend and baseline (spec sections 5.2 to 5.4)."""
from datetime import date, datetime, timedelta
from statistics import mean, median

from . import config


def local_day(ts: int) -> str:
    """Calendar day (YYYY-MM-DD) in local time."""
    return datetime.fromtimestamp(ts).date().isoformat()


def daily_values(readings) -> dict:
    """readings: iterable of (taken_at, k, valid). Returns {day: (median_k, n)}.

    Days with no valid reading are simply absent, never filled in.
    """
    by_day = {}
    for taken_at, k, valid in readings:
        if valid and k is not None:
            by_day.setdefault(local_day(taken_at), []).append(k)
    return {d: (median(ks), len(ks)) for d, ks in by_day.items()}


def smoothed(daily: dict, today: date):
    """Mean of up to the last 7 daily values inside the last 14 calendar days.

    daily: {day: k_day}. Needs at least 3 values, otherwise None.
    """
    window = ((today - timedelta(days=i)).isoformat() for i in range(config.SMOOTH_WINDOW_DAYS))
    values = [daily[d] for d in window if d in daily][:config.SMOOTH_DAYS]  # newest first
    if len(values) < config.SMOOTH_MIN_VALUES:
        return None
    return mean(values)


def baseline(daily: dict):
    """Mean of the first 14 daily values, or None until 14 exist."""
    days = sorted(daily)[: config.BASELINE_DAYS]
    if len(days) < config.BASELINE_DAYS:
        return None
    return mean(daily[d] for d in days)
