"""A virtual SootAble device: what the Arduino Nano + HM-10 would do.

It never touches the app's code. It only receives and returns raw bytes in
the frame format from the spec, so the app's parser, CRC check and sync logic
are exercised exactly as they would be against the real hardware.
"""
import math
import random

from . import frame as F

FW = 1
L_MM = 100
ADC_MAX = 1023
# The meters "in range" for the demo: (id the phone remembers a meter by, name it broadcasts).
# On real hardware the id is the Bluetooth address.
FLEET = [("SOOT-SIM-01", "SootAble-7F2A"), ("SOOT-SIM-02", "SootAble-3C91"), ("SOOT-SIM-03", "SootAble-B508")]
DEVICE_ID, ADV_NAME = FLEET[0]   # the first one is the demo meter that sample data and the developer tools drive


class VirtualDevice:
    def __init__(self, clock, seed: int = 1, device_id: str = DEVICE_ID, name: str = ADV_NAME):
        self.clock = clock
        self.device_id = device_id
        self.name = name
        self.rng = random.Random(seed)
        self._adv_rng = random.Random(99 + seed)   # separate, so a scan never changes the readings
        self.epoch = 1
        self.next_seq = 0
        self.records = []        # readings waiting for an ACK (the EEPROM store)
        self.parser = F.FrameParser()
        self.current_k = 1.4     # smoke level the next TRIGGER will measure
        self.current_flags = 0

    # --- what the sensor does ---
    def record(self, k: float, taken_at: float, flags: int = 0) -> int:
        """Store one measurement as raw ADC counts, like the firmware would."""
        i0 = 920 + self.rng.randint(-6, 6)
        i = max(1, round(i0 * math.exp(-k * L_MM / 1000)))
        if flags & F.NO_REF:
            i0 = i                       # purge failed: the "reference" is just the smoky reading
        if flags & F.SATURATED:
            i0, i = ADC_MAX - 2, ADC_MAX - 1
        seq = self.next_seq
        self.next_seq += 1
        self.records.append({"seq": seq, "taken_at": taken_at, "i0": i0, "i": i, "flags": flags})
        return seq

    def reboot(self):
        """Power cycle: the epoch counter goes up and sequence numbers restart."""
        self.epoch += 1
        self.next_seq = 0
        self.records = []

    # --- the serial link ---
    def advertise(self) -> dict:
        """What the meter broadcasts while it waits to be paired (its BLE advertisement)."""
        return {"id": self.device_id, "name": self.name, "rssi": -46 - self._adv_rng.randint(0, 24)}

    def hello(self) -> bytes:
        return F.build_hello(self.epoch, self.next_seq, FW, L_MM)

    def receive(self, data: bytes) -> bytes:
        """Bytes written by the phone. Returns whatever the device sends back."""
        out = b""
        for frame in self.parser.feed(data):
            if isinstance(frame, F.Sync):
                out += self._send_from(frame.from_seq)
            elif isinstance(frame, F.Ack):
                self.records = [r for r in self.records if r["seq"] > frame.up_to_seq]
            elif isinstance(frame, F.Trigger):
                seq = self.record(self.current_k, self.clock(), self.current_flags)
                out += self._send_from(seq)
        return out

    def _send_from(self, from_seq: int) -> bytes:
        now = self.clock()
        out = b""
        for r in self.records:
            if r["seq"] >= from_seq:
                age = max(0, int(now - r["taken_at"]))
                out += F.build_reading(r["seq"], age, r["i0"], r["i"], r["flags"])
        return out + F.build_end(self.epoch, max(self.next_seq - 1, 0))
