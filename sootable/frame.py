"""Build and parse the SootAble serial frames (spec section 4).

Every frame is laid out the same way:  0xA5 | type | payload (little-endian) | CRC-8 of everything before it.
The meter sends READING (one measurement), HELLO (firmware and chamber length) and END (nothing more to send);
the phone sends SYNC (send me readings from here), ACK (got them up to here) and TRIGGER (measure now).
"""
import struct
from dataclasses import dataclass

from .crc8 import crc8

SYNC_BYTE = 0xA5
T_READING, T_HELLO, T_END = 0x01, 0x02, 0x03
T_SYNC, T_ACK, T_TRIGGER = 0x10, 0x20, 0x30

# total frame length (sync + type + payload + crc) for each type
LENGTHS = {T_READING: 14, T_HELLO: 10, T_END: 7, T_SYNC: 5, T_ACK: 5, T_TRIGGER: 3}
BUFFER_CAP = 256

# flag bits
NO_REF, SATURATED, LOW_BATT, FAN_FAULT, MANUAL = 1, 2, 4, 8, 16
INVALID_FLAGS = NO_REF | SATURATED | FAN_FAULT


@dataclass
class Reading:
    seq: int
    age_s: int
    i0: int
    i: int
    flags: int


@dataclass
class Hello:
    epoch: int
    next_seq: int
    fw: int
    l_mm: int


@dataclass
class End:
    epoch: int
    last_seq: int


@dataclass
class Sync:
    from_seq: int


@dataclass
class Ack:
    up_to_seq: int


@dataclass
class Trigger:
    pass


def _wrap(ftype: int, payload: bytes) -> bytes:
    body = bytes([SYNC_BYTE, ftype]) + payload
    return body + bytes([crc8(body)])


def build_reading(seq, age_s, i0, i, flags=0) -> bytes:
    return _wrap(T_READING, struct.pack("<HIHHB", seq, age_s, i0, i, flags))


def build_hello(epoch, next_seq, fw, l_mm) -> bytes:
    return _wrap(T_HELLO, struct.pack("<HHBH", epoch, next_seq, fw, l_mm))


def build_end(epoch, last_seq) -> bytes:
    return _wrap(T_END, struct.pack("<HH", epoch, last_seq))


def build_sync(from_seq) -> bytes:
    return _wrap(T_SYNC, struct.pack("<H", from_seq))


def build_ack(up_to_seq) -> bytes:
    return _wrap(T_ACK, struct.pack("<H", up_to_seq))


def build_trigger() -> bytes:
    return _wrap(T_TRIGGER, b"")


def _decode(ftype: int, payload: bytes):
    if ftype == T_READING:
        return Reading(*struct.unpack("<HIHHB", payload))
    if ftype == T_HELLO:
        return Hello(*struct.unpack("<HHBH", payload))
    if ftype == T_END:
        return End(*struct.unpack("<HH", payload))
    if ftype == T_SYNC:
        return Sync(*struct.unpack("<H", payload))
    if ftype == T_ACK:
        return Ack(*struct.unpack("<H", payload))
    return Trigger()


class FrameParser:
    """Feed it bytes as they arrive; it returns whole, CRC-checked frames.

    BLE notifications hold at most 20 bytes, so a frame can arrive in pieces
    and several frames can arrive together. Bytes are buffered until a frame
    is complete.
    """

    def __init__(self):
        self.buf = bytearray()
        self.dropped = 0  # frames rejected for a bad CRC (shown in the UI)

    def feed(self, data: bytes) -> list:
        self.buf += data
        frames = []
        while True:
            start = self.buf.find(SYNC_BYTE)
            if start < 0:
                self.buf.clear()
                break
            del self.buf[:start]  # discard bytes in front of 0xA5
            if len(self.buf) < 2:
                break  # type byte has not arrived yet
            length = LENGTHS.get(self.buf[1])
            if length is None:
                del self.buf[0]  # unknown type: not a real frame start
                continue
            if len(self.buf) < length:
                break  # wait for the rest of the frame
            candidate = bytes(self.buf[:length])
            if crc8(candidate[:-1]) == candidate[-1]:
                frames.append(_decode(candidate[1], candidate[2:-1]))
                del self.buf[:length]
            else:
                self.dropped += 1
                del self.buf[0]  # drop only the 0xA5 and search again
        if len(self.buf) > BUFFER_CAP:
            self.buf.clear()
        return frames
