"""The phone side of the protocol: parse frames, save readings, run the sync (spec 4.6)."""
from . import config
from .frame import (End, FrameParser, Hello, Reading, build_ack, build_sync, build_trigger)
from .k import evaluate_reading, invalid_reason
from .link import hex_of


class PhoneSession:
    def __init__(self, store, device_id, clock, inspector):
        self.store = store
        self.device_id = device_id
        self.clock = clock
        self.inspector = inspector
        self.path_len_m = config.DEFAULT_PATH_LEN_M  # the device reports its own chamber length
        self.write = None             # set by the app: sends bytes to the device
        self.hello_next = 0           # next seq the device will assign
        self.epoch = 0
        self.reset()

    def reset(self):
        """Start of a new connection."""
        self.parser = FrameParser()
        self.complete = False
        self.kind = "sync"
        self.from_seq = 0
        self.saved = 0

    def begin_trigger(self):
        """Ask the device to measure now. The new reading will have seq = hello_next."""
        self.kind = "trigger"
        self.from_seq = self.hello_next
        self.complete = False
        self.saved = 0
        self.write(build_trigger())

    def on_bytes(self, chunk: bytes):
        before = self.parser.dropped
        for frame in self.parser.feed(chunk):
            self._handle(frame)
        if self.parser.dropped > before:
            self.inspector.add("app", hex_of(chunk), "CRC mismatch: corrupt frame dropped")

    def _handle(self, frame):
        if isinstance(frame, Hello):
            self.epoch = frame.epoch
            self.hello_next = frame.next_seq
            self.path_len_m = frame.l_mm / 1000
            self.from_seq = self.store.acked(self.device_id, frame.epoch) + 1
            self.store.touch_device(self.device_id, frame.epoch, frame.fw, int(self.clock()))
            self.store.forget_old_acks(self.device_id, frame.epoch)
            self.store.set_setting(f"chamber_mm:{self.device_id}", frame.l_mm)  # as reported by the meter
            self.inspector.add("app", "", f"{frame}: asking for readings from seq {self.from_seq}")
            self.write(build_sync(self.from_seq))
        elif isinstance(frame, Reading):
            self._save(frame)
        elif isinstance(frame, End):
            self._finish(frame)

    def _save(self, r: Reading):
        now = int(self.clock())
        k, valid = evaluate_reading(r.i0, r.i, r.flags, self.path_len_m)
        reason = invalid_reason(r.i0, r.i, r.flags)
        if valid and r.age_s > config.MAX_PAST_S:
            k, valid, reason = None, False, "Timestamp out of range"
        new = self.store.save_reading(self.device_id, self.epoch, r.seq, now - r.age_s, now,
                                      r.i0, r.i, r.flags, k, valid, reason)
        if new:
            self.saved += 1
        result = f"k = {k:.2f} m⁻¹" if valid else f"invalid ({reason})"
        dup = "" if new else " [duplicate, ignored]"
        self.inspector.add("app", "", f"READING seq={r.seq} i0={r.i0} i={r.i} flags=0x{r.flags:02X} → {result}{dup}")

    def _finish(self, end: End):
        """Acknowledge only up to the first gap, so a dropped frame is fetched again."""
        first = self.from_seq
        check = self.kind == "trigger" or self.hello_next > first
        last = end.last_seq if check else first - 1
        missing = next((s for s in range(first, last + 1)
                        if not self.store.has_reading(self.device_id, end.epoch, s)), None)
        ack_to = last if missing is None else missing - 1
        if ack_to >= first:
            self.store.set_acked(self.device_id, end.epoch, ack_to)  # also commits the whole sync
            self.inspector.add("app", "", f"{end}: all saved, acknowledging up to seq {ack_to}")
            self.write(build_ack(ack_to))
        else:
            self.inspector.add("app", "", f"{end}: nothing new to acknowledge")
        if missing is not None:
            self.inspector.add("app", "", f"seq {missing} is missing, will ask again")
        else:
            self.hello_next = max(self.hello_next, last + 1)
        self.complete = missing is None
