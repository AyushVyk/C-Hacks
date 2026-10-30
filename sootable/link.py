"""The simulated Bluetooth link between the app and the virtual device."""
import random
from collections import deque

from .frame import FrameParser

BLE_CHUNK = 20  # bytes per notification with the default MTU


class Inspector:
    """Keeps a log of every chunk on the link and every frame the app decodes."""

    def __init__(self, cap: int = 600):
        self.entries = deque(maxlen=cap)
        self.counter = 0

    def add(self, direction: str, hex_bytes: str = "", note: str = ""):
        self.counter += 1
        self.entries.append({"id": self.counter, "dir": direction, "hex": hex_bytes, "note": note})

    def since(self, last_id: int) -> list:
        return [e for e in self.entries if e["id"] > last_id]


def hex_of(data: bytes) -> str:
    return data.hex(" ").upper()


class SimTransport:
    """Moves bytes both ways, cutting them into BLE-sized chunks.

    chunk: "ble" (20 bytes), "byte" (1 byte at a time) or "random" (1 to 40 bytes,
    so frames are split and merged). corrupt_rate flips one bit in that share of
    chunks. drop_after_bytes kills the link once, part way through a sync.
    """

    def __init__(self, device, inspector, chunk="ble", corrupt_rate=0.0, drop_after_bytes=None, seed=3):
        self.device = device
        self.inspector = inspector
        self.chunk = chunk
        self.corrupt_rate = corrupt_rate
        self.drop_after_bytes = drop_after_bytes
        self.rng = random.Random(seed)
        self.on_bytes = None
        self.dead = False
        self.sent = 0

    def scan(self) -> list:
        """Meters in range, as a Bluetooth scan for the SootAble service (0xFFE0) would report them."""
        found = [self.device.advertise()]
        self.inspector.add("note", "", f"Scan: found {', '.join(d['name'] for d in found)}")
        return found

    def connect(self):
        self.dead = False
        self.sent = 0
        self.inspector.add("note", "", "Connected")
        self._deliver(self.device.hello())

    def write(self, data: bytes):
        if self.dead:
            raise ConnectionError("link is down")
        for pos in range(0, len(data), BLE_CHUNK):
            chunk = data[pos:pos + BLE_CHUNK]
            frames = FrameParser().feed(chunk)
            self.inspector.add("app→device", hex_of(chunk), repr(frames[0]) if frames else "")
            self._deliver(self.device.receive(chunk))

    def _size(self) -> int:
        if self.chunk == "byte":
            return 1
        if self.chunk == "random":
            return self.rng.randint(1, 40)
        return BLE_CHUNK

    def _deliver(self, data: bytes):
        pos = 0
        while pos < len(data) and not self.dead:
            chunk = bytearray(data[pos:pos + self._size()])
            pos += len(chunk)
            if self.drop_after_bytes is not None and self.sent + len(chunk) > self.drop_after_bytes:
                self.dead = True
                self.drop_after_bytes = None
                self.inspector.add("note", "", "LINK LOST before the sync finished")
                return
            self.sent += len(chunk)
            note = ""
            if self.rng.random() < self.corrupt_rate:
                chunk[self.rng.randrange(len(chunk))] ^= 1 << self.rng.randrange(8)
                note = "bit error injected on the link"
            self.inspector.add("device→app", hex_of(chunk), note)
            self.on_bytes(bytes(chunk))
