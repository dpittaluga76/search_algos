"""Experimental lean radix directory; existing baselines are unchanged."""

from bisect import bisect_left
from collections.abc import Callable, Sequence


def build_lean_radix_index(values: Sequence[int], *, bits: int = 10) -> Callable[[int], int | None]:
    """Borrow sorted unchanged integers, keeping exact first-index semantics.

    A smaller directory trades slightly wider C bisections for cheaper setup.
    Global endpoint guards ensure that the insertion index is always valid,
    even when it equals a bucket's stop. Equality still rejects absent keys.
    """
    if type(bits) is not int or not 0 <= bits <= 12:
        raise ValueError("bits must be an integer between 0 and 12")
    if not values:
        return lambda target: None
    lower, upper = values[0], values[-1]
    shift = max(0, (upper - lower).bit_length() - bits)
    count = ((upper - lower) >> shift) + 1
    offsets = [bisect_left(values, lower + (bucket << shift)) for bucket in range(count + 1)]

    def lookup(target: int, _search: Callable[..., int] = bisect_left) -> int | None:
        if target < lower or target > upper:
            return None
        bucket = (target - lower) >> shift
        index = _search(values, target, offsets[bucket], offsets[bucket + 1])
        return index if values[index] == target else None

    return lookup
