from datetime import date

import pytest

from sootable import alerts, config, daily
from sootable.crc8 import crc8
from sootable.frame import (Ack, End, FrameParser, Hello, NO_REF, Reading, Sync, Trigger,
                            build_ack, build_end, build_hello, build_reading, build_sync,
                            build_trigger)
from sootable.k import evaluate_reading


def h(s):
    return bytes.fromhex(s.replace(" ", ""))


# --- spec section 4.5 test vectors ---
def test_crc_check_value():
    assert crc8(b"123456789") == 0xF4


VECTORS = [
    (build_reading(5, 3600, 920, 720, 0), "A5 01 05 00 10 0E 00 00 98 03 D0 02 00 0F"),
    (build_reading(6, 86400, 920, 800, 0), "A5 01 06 00 80 51 01 00 98 03 20 03 00 33"),
    (build_reading(7, 120, 910, 910, NO_REF), "A5 01 07 00 78 00 00 00 8E 03 8E 03 01 76"),
    (build_hello(3, 6, 1, 100), "A5 02 03 00 06 00 01 64 00 62"),
    (build_end(3, 6), "A5 03 03 00 06 00 B8"),
    (build_sync(6), "A5 10 06 00 6D"),
    (build_ack(5), "A5 20 05 00 B3"),
    (build_trigger(), "A5 30 C9"),
]


@pytest.mark.parametrize("built,expected", VECTORS)
def test_builders_match_spec_bytes(built, expected):
    assert built == h(expected)


@pytest.mark.parametrize("built,expected", VECTORS)
def test_parser_reads_spec_bytes(built, expected):
    assert len(FrameParser().feed(h(expected))) == 1


def test_parsed_fields():
    p = FrameParser()
    assert p.feed(h("A5 01 05 00 10 0E 00 00 98 03 D0 02 00 0F")) == [Reading(5, 3600, 920, 720, 0)]
    assert p.feed(h("A5 02 03 00 06 00 01 64 00 62")) == [Hello(3, 6, 1, 100)]
    assert p.feed(h("A5 03 03 00 06 00 B8")) == [End(3, 6)]
    assert p.feed(h("A5 10 06 00 6D")) == [Sync(6)]
    assert p.feed(h("A5 20 05 00 B3")) == [Ack(5)]
    assert p.feed(h("A5 30 C9")) == [Trigger()]


def test_k_values():
    assert evaluate_reading(920, 720, 0)[0] == pytest.approx(2.4512, abs=1e-4)
    assert evaluate_reading(920, 800, 0)[0] == pytest.approx(1.3976, abs=1e-4)
    assert evaluate_reading(910, 910, NO_REF) == (None, False)


def test_boundary_exactly_on_limit_is_not_over():
    k, _ = evaluate_reading(920, 720, 0)
    assert k > 2.45  # unrounded is above the limit ...
    assert alerts.status(k, 2.45) == alerts.WATCH  # ... but rounded 2.45 is not over
    assert alerts.status(2.46, 2.45) == alerts.OVER


def test_validity_rules():
    assert evaluate_reading(199, 100, 0) == (None, False)  # reference too low
    assert evaluate_reading(900, 0, 0) == (None, False)    # i of zero
    assert evaluate_reading(900, 906, 0) == (None, False)  # i above i0 by more than 5
    assert evaluate_reading(900, 905, 0) == (0.0, True)    # within noise, k = 0
    assert evaluate_reading(900, 800, 2) == (None, False)  # SATURATED
    assert evaluate_reading(900, 800, 8) == (None, False)  # FAN_FAULT
    assert evaluate_reading(900, 800, 4)[1] is True        # LOW_BATT alone is fine


# --- parser robustness ---
STREAM = b"".join(b for b, _ in VECTORS)


def test_split_at_every_byte_boundary():
    for cut in range(1, len(STREAM)):
        p = FrameParser()
        got = p.feed(STREAM[:cut]) + p.feed(STREAM[cut:])
        assert len(got) == len(VECTORS), cut


def test_one_byte_at_a_time():
    p = FrameParser()
    got = []
    for b in STREAM:
        got += p.feed(bytes([b]))
    assert len(got) == len(VECTORS)


def test_several_frames_in_one_chunk():
    assert len(FrameParser().feed(STREAM)) == len(VECTORS)


def test_garbage_before_frame_is_discarded():
    assert len(FrameParser().feed(b"\x00\x11\x22" + VECTORS[0][0])) == 1


def test_corrupt_frame_dropped_next_good_frame_read():
    bad = bytearray(VECTORS[0][0])
    bad[6] ^= 0x01
    p = FrameParser()
    assert p.feed(bytes(bad) + VECTORS[1][0]) == [Reading(6, 86400, 920, 800, 0)]
    assert p.dropped == 1


def test_every_single_bit_flip_is_caught():
    frame = VECTORS[0][0]
    for byte in range(len(frame)):
        for bit in range(8):
            bad = bytearray(frame)
            bad[byte] ^= 1 << bit
            assert Reading(5, 3600, 920, 720, 0) not in FrameParser().feed(bytes(bad))


def test_buffer_is_capped():
    p = FrameParser()
    p.feed(b"\xA5\x01" + b"\x00" * 300)
    assert len(p.buf) <= 256


# --- daily / smoothing / baseline ---
def test_daily_is_median_of_valid_only():
    base = 1_800_000_000
    rows = [(base, 1.0, True), (base + 60, 3.0, True), (base + 120, 2.0, True),
            (base + 180, 9.9, False)]
    ((day, (k, n)),) = daily.daily_values(rows).items()
    assert (k, n) == (2.0, 3)


def test_smoothed_needs_three_values_and_uses_window():
    today = date(2026, 10, 30)
    assert daily.smoothed({"2026-10-30": 1.0, "2026-10-29": 1.0}, today) is None
    vals = {f"2026-10-{d}": float(d - 20) for d in range(21, 31)}  # 10 days: 1..10
    assert daily.smoothed(vals, today) == pytest.approx(sum(range(4, 11)) / 7)  # last 7
    old = {"2026-10-01": 5.0, "2026-10-02": 5.0, "2026-10-03": 5.0}  # outside 14 days
    assert daily.smoothed(old, today) is None


def test_baseline_needs_14_values_and_is_first_14():
    d = {f"2026-09-{i:02d}": 1.0 for i in range(1, 14)}
    assert daily.baseline(d) is None
    d["2026-09-14"] = 1.0
    d["2026-09-20"] = 99.0  # later value must not change the baseline
    assert daily.baseline(d) == 1.0


# --- alerts ---
def test_status_bands():
    assert alerts.status(1.95, 2.45) == alerts.OK
    assert alerts.status(1.96, 2.45) == alerts.WATCH
    assert alerts.status(2.45, 2.45) == alerts.WATCH
    assert alerts.status(None, 2.45) is None


def test_rise_rule():
    rising = [1.4, 1.5, 1.7, 1.9, 2.1, 2.3]
    assert alerts.rise_detected(2.2, 1.4, rising)
    assert not alerts.rise_detected(1.9, 1.4, rising)  # below 1.5 x baseline
    assert not alerts.rise_detected(2.2, 1.4, [2.3, 2.2, 2.3, 2.2, 2.3, 2.2])  # not rising


def test_notify_only_on_change_and_cooldown():
    now = 1_000_000
    assert alerts.new_alerts(alerts.OK, alerts.OK, False, False, {}, now) == []
    assert alerts.new_alerts(alerts.OK, alerts.WATCH, False, False, {}, now) == [("WATCH", True)]
    # went down and up again inside 7 days: logged, not notified
    assert alerts.new_alerts(alerts.OK, alerts.WATCH, False, False, {"WATCH": now - 86400}, now) \
        == [("WATCH", False)]
    # after 7 days it notifies again
    assert alerts.new_alerts(alerts.OK, alerts.WATCH, False, False,
                             {"WATCH": now - config.ALERT_COOLDOWN_S}, now) == [("WATCH", True)]
    assert alerts.new_alerts(alerts.WATCH, alerts.OVER, False, False, {}, now) == [("OVER", True)]
    assert alerts.new_alerts(alerts.OVER, alerts.OVER, False, False, {}, now) == []


def test_alert_status_has_hysteresis():
    limit = 2.45
    assert alerts.settle(alerts.OVER, alerts.WATCH, 2.44, limit) == alerts.OVER   # hovering at the limit
    assert alerts.settle(alerts.OVER, alerts.WATCH, 2.30, limit) == alerts.WATCH  # clearly below (< 2.3275)
    assert alerts.settle(alerts.OK, alerts.OVER, 2.60, limit) == alerts.OVER      # goes up at once
    assert alerts.settle(alerts.WATCH, alerts.OK, 1.95, limit) == alerts.WATCH
    assert alerts.settle(alerts.WATCH, alerts.OK, 1.80, limit) == alerts.OK
    assert alerts.settle(alerts.OVER, None, None, limit) is None


def test_single_high_reading_is_neutral():
    assert alerts.home_note(3.5, alerts.OK, 2.45) == "One high reading today, check again tomorrow."
    assert alerts.home_note(3.5, alerts.OVER, 2.45) is None
    assert alerts.home_note(1.4, alerts.OK, 2.45) is None
