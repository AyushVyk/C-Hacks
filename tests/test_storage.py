import os
import time

from sootable import config, engine
from sootable.app import SootableApp
from sootable.store import Store

DAY = 86400


def fill_years(store, years, now):
    """One valid reading a day for `years` years, oldest first, around k = 1.4."""
    n = years * 365
    for j in range(n):
        taken = now - (n - 1 - j) * DAY - 120
        store.save_reading("SOOT-SIM-01", 1, j, taken, taken, 920, 800, 0, 1.3976, True, None)


def test_five_years_of_daily_readings_stay_small():
    store = Store(":memory:")
    now = time.time()
    fill_years(store, 5, now)
    engine.ensure_baseline(store)
    store.prune(now)
    rows = store.readings()
    assert len(rows) == config.RETENTION_DAYS == 1000
    assert store.size_bytes() < 250 * 1024  # a quarter of a megabyte for the whole database


def test_long_term_scenario_keeps_1000_days_and_is_fast():
    from sootable import scenarios
    app = SootableApp(Store(":memory:"))
    start = time.time()
    scenarios.run(app, "long_term")
    state = engine.summary(app.store, time.time())
    engine.trend(app.store, time.time(), 1000)
    assert len(app.store.readings()) == 1000
    assert state["status"] == "OVER"
    # a low baseline means RISE (1.5 x baseline) is reached before WATCH (80% of the limit)
    types = [a["type"] for a in sorted(app.store.alerts(), key=lambda a: a["created_at"])]
    assert types == ["RISE", "WATCH", "OVER"]
    assert all(a["delivered"] for a in app.store.alerts())
    assert time.time() - start < 5


def test_baseline_survives_pruning_the_readings_it_came_from():
    store = Store(":memory:")
    now = time.time()
    fill_years(store, 3, now)
    engine.ensure_baseline(store)
    saved = float(store.vget(store.active_vehicle_id(), "baseline_k"))
    store.prune(now)
    assert saved == 1.3976 and engine.baseline_of(store, engine.daily_k(store)) == saved
    # pruned history still replays without crashing or inventing alerts
    assert engine.refresh_alerts(store) == []


def test_alerts_log_is_capped():
    store = Store(":memory:")
    for j in range(config.MAX_ALERTS + 50):
        store.add_alert(j, f"day{j}", "WATCH", 2.0, "m", False)
    store.prune(time.time())
    assert len(store.alerts()) == config.MAX_ALERTS


def test_file_shrinks_after_pruning(tmp_path):
    path = str(tmp_path / "s.db")
    store = Store(path)
    now = time.time()
    fill_years(store, 5, now)
    store.db.commit()
    big = os.path.getsize(path)
    store.prune(now)
    assert os.path.getsize(path) < big * 0.8  # 1825 days written, 1000 kept


def test_old_epoch_ack_markers_are_removed_after_reboot():
    from sootable import scenarios
    app = SootableApp(Store(":memory:"))
    scenarios.run(app, "epoch_change")
    acks = [r[0] for r in app.store.db.execute("SELECT key FROM setting WHERE key LIKE 'ack:%'")]
    assert acks == ["ack:SOOT-SIM-01:2"]
