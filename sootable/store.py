"""Local SQLite storage (spec section 6). The daily values are computed on the fly."""
import os
import sqlite3

from . import config

SCHEMA_V1 = """
CREATE TABLE vehicle (id INTEGER PRIMARY KEY, name TEXT, limit_k REAL, path_len_m REAL, created_at INTEGER);
CREATE TABLE device (id TEXT PRIMARY KEY, name TEXT, last_epoch INTEGER, last_seen_at INTEGER, fw INTEGER);
CREATE TABLE reading (
  id INTEGER PRIMARY KEY, device_id TEXT, epoch INTEGER, seq INTEGER, taken_at INTEGER,
  received_at INTEGER, i0 INTEGER, i INTEGER, flags INTEGER, k REAL, valid INTEGER, reason TEXT,
  UNIQUE(device_id, epoch, seq));
CREATE TABLE alert (
  id INTEGER PRIMARY KEY, created_at INTEGER, day TEXT, type TEXT, k_smooth REAL,
  message TEXT, delivered INTEGER, UNIQUE(type, day));
CREATE TABLE setting (key TEXT PRIMARY KEY, value TEXT);
"""

# Version 2: several vehicles. Each reading and alert belongs to a vehicle, and the meter is
# linked to the vehicle it is currently on.
SCHEMA_V2 = """
ALTER TABLE reading ADD COLUMN vehicle_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE device ADD COLUMN vehicle_id INTEGER NOT NULL DEFAULT 1;
CREATE TABLE alert2 (
  id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL DEFAULT 1, created_at INTEGER, day TEXT, type TEXT,
  k_smooth REAL, message TEXT, delivered INTEGER, UNIQUE(vehicle_id, type, day));
INSERT INTO alert2 (id, created_at, day, type, k_smooth, message, delivered)
  SELECT id, created_at, day, type, k_smooth, message, delivered FROM alert;
DROP TABLE alert;
ALTER TABLE alert2 RENAME TO alert;
CREATE INDEX reading_vehicle ON reading (vehicle_id, taken_at);
"""
# Version 3: what kind of vehicle it is (shown as its icon).
SCHEMA_V3 = "ALTER TABLE vehicle ADD COLUMN kind TEXT NOT NULL DEFAULT 'car';"

# Version 4: several meters. A meter is "paired" once the owner has connected it to a vehicle (the device row's
# vehicle_id says which). The old single "paired_device" setting becomes a flag on that device.
SCHEMA_V4 = """
ALTER TABLE device ADD COLUMN paired INTEGER NOT NULL DEFAULT 0;
UPDATE device SET paired = 1 WHERE id IN (SELECT value FROM setting WHERE key = 'paired_device');
DELETE FROM setting WHERE key = 'paired_device';
"""
MIGRATIONS = [(1, SCHEMA_V1), (2, SCHEMA_V2), (3, SCHEMA_V3), (4, SCHEMA_V4)]

KINDS = ("car", "suv", "truck", "auto")
KEEP_SETTINGS = ("onboarded", "active_vehicle")
DEFAULT_VEHICLE_NAME = "My vehicle"


class Store:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA auto_vacuum = INCREMENTAL")  # lets the file shrink; set before tables exist
        self._migrate()

    def _migrate(self):
        self.db.execute("CREATE TABLE IF NOT EXISTS migrations (version INTEGER PRIMARY KEY)")
        done = {r[0] for r in self.db.execute("SELECT version FROM migrations")}
        for version, sql in MIGRATIONS:
            if version not in done:
                self.db.executescript(sql)
                self.db.execute("INSERT INTO migrations VALUES (?)", (version,))
        if not self.db.execute("SELECT 1 FROM vehicle").fetchone():
            self._insert_vehicle(DEFAULT_VEHICLE_NAME)
        self.db.commit()

    # ---------- vehicles ----------
    def _insert_vehicle(self, name, kind="car") -> int:
        cur = self.db.execute("INSERT INTO vehicle (name, limit_k, path_len_m, created_at, kind)"
                              " VALUES (?, ?, ?, strftime('%s','now'), ?)",
                              (name, config.DEFAULT_LIMIT_K, config.DEFAULT_PATH_LEN_M,
                               kind if kind in KINDS else "car"))
        return cur.lastrowid

    def vehicles(self) -> list:
        return [dict(r) for r in self.db.execute("SELECT * FROM vehicle ORDER BY id")]

    def active_vehicle_id(self) -> int:
        """The vehicle the screens are showing. Falls back to the first one."""
        ids = [v["id"] for v in self.vehicles()]
        chosen = self.get_setting("active_vehicle")
        return int(chosen) if chosen is not None and int(chosen) in ids else ids[0]

    def set_active_vehicle(self, vid: int):
        self.set_setting("active_vehicle", vid)

    def vehicle(self, vid=None) -> dict:
        vid = vid or self.active_vehicle_id()
        return dict(self.db.execute("SELECT * FROM vehicle WHERE id = ?", (vid,)).fetchone())

    def add_vehicle(self, name, kind="car") -> int:
        vid = self._insert_vehicle(name, kind)
        self.db.commit()
        return vid

    def rename_vehicle(self, name, vid=None, kind=None):
        """The limit is the legal one and the chamber length belongs to the device, so only the name
        (and the kind of vehicle, which is just its icon) can change."""
        vid = vid or self.active_vehicle_id()
        self.db.execute("UPDATE vehicle SET name=? WHERE id=?", (name, vid))
        if kind in KINDS:
            self.db.execute("UPDATE vehicle SET kind=? WHERE id=?", (kind, vid))
        self.db.commit()

    def clear_vehicle_data(self, vid: int):
        """Forget one vehicle's readings, alerts and per-vehicle settings. The vehicle and the others stay."""
        self.db.execute("DELETE FROM reading WHERE vehicle_id=?", (vid,))
        self.db.execute("DELETE FROM alert WHERE vehicle_id=?", (vid,))
        self.db.execute("DELETE FROM setting WHERE key LIKE ?", (f"%:v{vid}",))
        self.db.commit()

    def delete_vehicle(self, vid: int) -> bool:
        """Remove a vehicle and everything recorded for it. The last vehicle cannot be removed."""
        if len(self.vehicles()) < 2:
            return False
        self.db.execute("DELETE FROM reading WHERE vehicle_id=?", (vid,))
        self.db.execute("DELETE FROM alert WHERE vehicle_id=?", (vid,))
        self.db.execute("DELETE FROM setting WHERE key LIKE ?", (f"%:v{vid}",))
        self.db.execute("DELETE FROM vehicle WHERE id=?", (vid,))
        for row in self.db.execute("SELECT id FROM device WHERE vehicle_id=?", (vid,)).fetchall():
            self._forget_device(row[0])          # its meter goes back to being unassigned
        if self.get_setting("active_vehicle") == str(vid):
            self.db.execute("DELETE FROM setting WHERE key='active_vehicle'")
        self.db.commit()
        return True

    # ---------- settings (global, and per vehicle) ----------
    def get_setting(self, key, default=None):
        row = self.db.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO setting VALUES (?, ?)", (key, str(value)))
        self.db.commit()

    def vget(self, vid, key, default=None):
        return self.get_setting(f"{key}:v{vid}", default)

    def vset(self, vid, key, value):
        self.set_setting(f"{key}:v{vid}", value)

    def vdel(self, vid, key):
        self.db.execute("DELETE FROM setting WHERE key=?", (f"{key}:v{vid}",))
        self.db.commit()

    # ---------- device and sync bookkeeping ----------
    def touch_device(self, device_id, epoch, fw, now):
        """Record a connection. A new meter is linked to the vehicle being viewed; an existing link stays."""
        self.db.execute(
            "INSERT INTO device (id, name, last_epoch, last_seen_at, fw, vehicle_id) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET last_epoch=excluded.last_epoch, last_seen_at=excluded.last_seen_at, fw=excluded.fw",
            (device_id, device_id, epoch, now, fw, self.active_vehicle_id()))
        self.db.commit()

    def device(self, device_id):
        row = self.db.execute("SELECT * FROM device WHERE id=?", (device_id,)).fetchone()
        return dict(row) if row else None

    def set_device_name(self, device_id, name):
        self.db.execute("UPDATE device SET name=? WHERE id=?", (name, device_id))
        self.db.commit()

    def _forget_device(self, device_id):
        self.db.execute("DELETE FROM device WHERE id=?", (device_id,))
        self.db.execute("DELETE FROM setting WHERE key LIKE ? OR key=?", (f"ack:{device_id}:%", f"chamber_mm:{device_id}"))

    def forget_device(self, device_id):
        """Unpair: forget the meter and its sync bookkeeping. Readings already saved are kept."""
        self._forget_device(device_id)
        self.db.commit()

    def devices(self) -> list:
        """Every meter that has been paired to a vehicle."""
        return [dict(r) for r in self.db.execute("SELECT * FROM device WHERE paired=1 ORDER BY id")]

    def device_for_vehicle(self, vid: int):
        """The meter paired to a vehicle, or None. A vehicle has at most one."""
        row = self.db.execute("SELECT * FROM device WHERE paired=1 AND vehicle_id=? ORDER BY id LIMIT 1", (vid,)).fetchone()
        return dict(row) if row else None

    def set_paired(self, device_id, paired: bool = True):
        self.db.execute("UPDATE device SET paired=? WHERE id=?", (int(paired), device_id))
        self.db.commit()

    def device_vehicle(self, device_id) -> int:
        """The vehicle the meter is currently on."""
        row = self.db.execute("SELECT vehicle_id FROM device WHERE id=?", (device_id,)).fetchone()
        ids = [v["id"] for v in self.vehicles()]
        return row[0] if row and row[0] in ids else self.active_vehicle_id()

    def link_device(self, device_id, vid: int):
        self.db.execute("INSERT INTO device (id, name, vehicle_id) VALUES (?,?,?)"
                        " ON CONFLICT(id) DO UPDATE SET vehicle_id=excluded.vehicle_id", (device_id, device_id, vid))
        self.db.commit()

    def acked(self, device_id, epoch) -> int:
        """Highest seq the phone has acknowledged for this device and epoch (-1 if none)."""
        return int(self.get_setting(f"ack:{device_id}:{epoch}", -1))

    def set_acked(self, device_id, epoch, seq):
        self.set_setting(f"ack:{device_id}:{epoch}", seq)

    # ---------- readings ----------
    def save_reading(self, device_id, epoch, seq, taken_at, received_at, i0, i, flags, k, valid, reason,
                     vehicle_id=None):
        """Returns False when the (device, epoch, seq) key already exists."""
        vehicle_id = vehicle_id or self.device_vehicle(device_id)
        cur = self.db.execute(
            "INSERT OR IGNORE INTO reading (device_id, epoch, seq, taken_at, received_at, i0, i, flags,"
            " k, valid, reason, vehicle_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (device_id, epoch, seq, taken_at, received_at, i0, i, flags, k, int(valid), reason, vehicle_id))
        return cur.rowcount == 1  # committed once per sync (in the ack), not once per reading

    def has_reading(self, device_id, epoch, seq) -> bool:
        return self.db.execute("SELECT 1 FROM reading WHERE device_id=? AND epoch=? AND seq=?",
                               (device_id, epoch, seq)).fetchone() is not None

    def readings(self, vid=None) -> list:
        """All readings, or one vehicle's, oldest first."""
        if vid is None:
            rows = self.db.execute("SELECT * FROM reading ORDER BY taken_at, id")
        else:
            rows = self.db.execute("SELECT * FROM reading WHERE vehicle_id=? ORDER BY taken_at, id", (vid,))
        return [dict(r) for r in rows]

    # ---------- alerts ----------
    def add_alert(self, created_at, day, type_, k_smooth, message, delivered, vehicle_id=None) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO alert (vehicle_id, created_at, day, type, k_smooth, message,"
                              " delivered) VALUES (?,?,?,?,?,?,?)",
                              (vehicle_id or self.active_vehicle_id(), created_at, day, type_, k_smooth, message,
                               int(delivered)))
        self.db.commit()
        return cur.rowcount == 1

    def alerts(self, vid=None) -> list:
        if vid is None:
            rows = self.db.execute("SELECT * FROM alert ORDER BY created_at DESC, id DESC")
        else:
            rows = self.db.execute("SELECT * FROM alert WHERE vehicle_id=? ORDER BY created_at DESC, id DESC", (vid,))
        return [dict(r) for r in rows]

    # ---------- housekeeping ----------
    def prune(self, now: float):
        """Keep storage small: drop readings past retention, trim each alerts log, shrink the file."""
        cutoff = int(now) - config.RETENTION_DAYS * 86400
        self.db.execute("DELETE FROM reading WHERE taken_at < ?", (cutoff,))
        self.db.execute("DELETE FROM alert WHERE id NOT IN (SELECT id FROM ("
                        " SELECT id, ROW_NUMBER() OVER (PARTITION BY vehicle_id ORDER BY created_at DESC, id DESC) AS n"
                        " FROM alert) WHERE n <= ?)", (config.MAX_ALERTS,))
        self.db.commit()
        self.db.execute("PRAGMA incremental_vacuum").fetchall()  # frees pages as the rows are read

    def forget_old_acks(self, device_id, current_epoch):
        """After a reboot the device starts a new epoch, so older ack markers are no longer needed."""
        self.db.execute("DELETE FROM setting WHERE key LIKE ? AND key != ?",
                        (f"ack:{device_id}:%", f"ack:{device_id}:{current_epoch}"))
        self.db.commit()

    def size_bytes(self) -> int:
        """Bytes of data in use (pages not on the free list)."""
        pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        free = self.db.execute("PRAGMA freelist_count").fetchone()[0]
        return (pages - free) * self.db.execute("PRAGMA page_size").fetchone()[0]

    def clear_readings_and_alerts(self):
        """Forget every reading, alert and per-vehicle setting. Vehicles and the chosen one stay."""
        for table in ("reading", "alert", "device"):
            self.db.execute(f"DELETE FROM {table}")
        marks = ",".join("?" * len(KEEP_SETTINGS))
        self.db.execute(f"DELETE FROM setting WHERE key NOT IN ({marks})", KEEP_SETTINGS)
        self.db.commit()

    def wipe_everything(self):
        """Delete all data, including the extra vehicles, and start again with one."""
        for table in ("reading", "alert", "device", "setting", "vehicle"):
            self.db.execute(f"DELETE FROM {table}")
        self._insert_vehicle(DEFAULT_VEHICLE_NAME)
        self.db.commit()
