"""Sprint-only exact stride and radix candidates; no baseline replacement."""

from bisect import bisect_left
from collections.abc import Callable, Sequence


def build_stride_probe(values: Sequence[int]) -> Callable[[int], int | None]:
    if not values:
        return lambda target: None
    n = len(values)
    low, high = values[0], values[-1]
    if low == high:
        return lambda target: 0 if target == low else None
    step = max(1, (high - low) // (n - 1))

    def lookup(target: int) -> int | None:
        if target < low or target > high:
            return None
        p = min(n - 1, (target - low) // step)
        value = values[p]
        if value == target:
            if p == 0 or values[p - 1] < target:
                return p
            return bisect_left(values, target, 0, p)
        if value < target:
            if p + 1 == n or values[p + 1] > target:
                return None
            lo, hi = p + 1, n
        else:
            if p == 0 or values[p - 1] < target:
                return None
            lo, hi = 0, p
        i = bisect_left(values, target, lo, hi)
        return i if i < hi and values[i] == target else None

    return lookup


def build_stride_exact_endpoints(values: Sequence[int]) -> Callable[[int], int | None]:
    """Endpoint-derived stride only predicts; neighbors certify every query."""
    n = len(values)
    if n < 2 or values[-1] == values[0]:
        return build_stride_probe(values)
    low, high = values[0], values[-1]
    step, remainder = divmod(high - low, n - 1)
    if remainder or not step:
        return build_compact_radix(values)

    def lookup(target: int) -> int | None:
        if target < low or target > high:
            return None
        p = (target - low) // step
        value = values[p]
        if value == target:
            if p == 0 or values[p - 1] < target:
                return p
            return bisect_left(values, target, 0, p)
        if value < target:
            if p + 1 == n or values[p + 1] > target:
                return None
            lo, hi = p + 1, n
        else:
            if p == 0 or values[p - 1] < target:
                return None
            lo, hi = 0, p
        i = bisect_left(values, target, lo, hi)
        return i if i < hi and values[i] == target else None

    return lookup


def build_compact_radix(values: Sequence[int], bits: int = 10) -> Callable[[int], int | None]:
    if not values:
        return lambda target: None
    low, high = values[0], values[-1]
    shift = max(0, (high - low).bit_length() - bits)
    count = ((high - low) >> shift) + 1
    offsets = [bisect_left(values, low + (bucket << shift)) for bucket in range(count + 1)]
    ranges = tuple(zip(offsets, offsets[1:]))

    def lookup(target: int) -> int | None:
        if target < low or target > high:
            return None
        left, right = ranges[(target - low) >> shift]
        index = bisect_left(values, target, left, right)
        return index if index < right and values[index] == target else None

    return lookup
