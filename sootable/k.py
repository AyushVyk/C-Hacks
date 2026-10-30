"""Per-reading opacity coefficient (spec section 5.1)."""
import math

from . import config
from .frame import FAN_FAULT, NO_REF, SATURATED


def evaluate_reading(i0: int, i: int, flags: int, path_len_m: float = config.DEFAULT_PATH_LEN_M):
    """Return (k, valid). k is None when it cannot be computed."""
    if invalid_reason(i0, i, flags):
        return None, False
    if i >= i0:
        return 0.0, True  # within noise of clean air
    return -(1.0 / path_len_m) * math.log(i / i0), True


def invalid_reason(i0: int, i: int, flags: int):
    """Why a reading is invalid, or None if it is valid."""
    if flags & NO_REF:
        return "No clean-air reference was taken"
    if flags & SATURATED:
        return "Sensor saturated"
    if flags & FAN_FAULT:
        return "Fan fault"
    if i0 < config.MIN_I0:
        return "Reference reading too low"
    if i <= 0:
        return "No light reached the sensor"
    if i > i0 + config.NOISE_TOLERANCE:
        return "Smoky reading brighter than clean air"
    return None
