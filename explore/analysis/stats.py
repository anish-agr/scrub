"""Small statistics helpers shared by the reports."""

from __future__ import annotations

import math


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson 95% interval for k successes in n tries, or None when n is 0."""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def pct(values: list[float], q: float) -> float | None:
    """q-th percentile (0-100) with linear interpolation, None for no values."""
    v = sorted(x for x in values if isinstance(x, (int, float)))
    if not v:
        return None
    i = (len(v) - 1) * q / 100
    lo, hi = math.floor(i), math.ceil(i)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def median(values: list[float]) -> float | None:
    return pct(values, 50)
