from __future__ import annotations

import math


def round_to_tick(price: float, tick_size: float) -> float:
    return round(round(price / tick_size) * tick_size, 12)


def floor_to_tick(price: float, tick_size: float) -> float:
    return round(math.floor(price / tick_size) * tick_size, 12)


def ceil_to_tick(price: float, tick_size: float) -> float:
    return round(math.ceil(price / tick_size) * tick_size, 12)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

