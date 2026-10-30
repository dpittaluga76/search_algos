"""Exact local representations behind a radix directory for integer search.

This experimental strategy leaves the existing radix and prepared strategies
unchanged. Input sorting, integer values and targets, and unchanged input during
lookup are preconditions. Preparation scans the values to certify the local
shortcuts, rather than inferring their correctness from samples.
"""

from bisect import bisect_left
from collections.abc import Callable, Sequence
from typing import NamedTuple

_MAX_BITMAP_WIDTH = 256


class _Bucket(NamedTuple):
    lower: int
    upper: int
    step: int
    mask: int
    first_indices: tuple[int, ...]
    start: int
    stop: int


def _certify_bucket(values: list[int], positions: list[int], stop: int) -> _Bucket:
    """Choose a representation after collecting every distinct bucket value."""
    lower, upper, start = values[0], values[-1], positions[0]
    if len(values) == 1:
        return _Bucket(lower, upper, 1, 0, (), start, stop)

    step = values[1] - lower
    regular = all(values[index] - values[index - 1] == step for index in range(2, len(values)))
    if regular:
        # Unique progressions use original index = start + distinct rank. A
        # duplicate run may have any length, so otherwise retain first indices.
        first_indices = () if stop - start == len(values) else tuple(positions)
        return _Bucket(lower, upper, step, 0, first_indices, start, stop)

    if upper - lower < _MAX_BITMAP_WIDTH:
        mask = 0
        for value in values:
            mask |= 1 << (value - lower)
        return _Bucket(lower, upper, 0, mask, tuple(positions), start, stop)

    # Wide, irregular buckets keep no per-key metadata. They borrow the input
    # and use an ordinary lower-bound search restricted to this bucket.
    return _Bucket(lower, upper, 0, 0, (), start, stop)


def build_certified_radix_index(
    input_list: Sequence[int], *, bits: int = 12
) -> Callable[[int], int | None]:
    """Prepare exact per-bucket shortcuts for first-index integer lookups.

    The ascending integer input must remain unchanged while the returned
    callable is used. Integer lookup targets are required. These are unchecked
    preconditions, as for ``build_radix_index``; the preparation scan certifies
    representation properties, not the input contract.

    ``bits`` must be an integer from 0 through 12, excluding Boolean values.
    The same value-space partition as radix uses at most ``2**bits`` buckets.
    Each bucket uses a verified arithmetic progression of distinct values, a
    membership bitmap of at most 256 bits, or bounded ``bisect_left``. Empty
    buckets return no match. Singleton buckets compare directly. Duplicate
    progressions and bitmaps retain each distinct value's first original index.

    Preparation uses O(n + B) work and O(B + u) peak additional storage for n
    input elements, B buckets and u distinct values. Unique progressions and
    fallback buckets discard per-key metadata. Temporary lists hold distinct
    values and their first indices for the current bucket; with one all-unique
    bucket they can contain n entries each. The input is never sliced or
    mutated. Empty and constant input have constant-cost fast paths.

    Arithmetic and bitmap lookup need bounded work for fixed-size integer keys;
    fallback lookup uses O(log(m + 1)) sequence accesses in a bucket of m values,
    O(log n) in the worst case. Python integer arithmetic additionally depends
    on operand size. Full preparation and dispatch overhead may outweigh lookup
    savings, especially for few queries or wide, irregular buckets.

    >>> lookup = build_certified_radix_index([20, 23, 23, 26], bits=0)
    >>> lookup(23)
    1
    >>> lookup(24)
    >>> build_certified_radix_index([-12, -12, -4, 3], bits=0)(-12)
    0
    >>> build_certified_radix_index([])(1)
    """
    if type(bits) is not int or not 0 <= bits <= 12:
        raise ValueError("bits must be an integer between 0 and 12")
    size = len(input_list)
    if size == 0:
        return lambda target: None

    lower, upper = input_list[0], input_list[-1]
    if lower == upper:
        return lambda target: 0 if target == lower else None
    shift = max(0, (upper - lower).bit_length() - bits)
    bucket_count = ((upper - lower) >> shift) + 1
    directory: list[_Bucket | None] = [None] * bucket_count

    current_bucket = 0
    values, positions = [lower], [0]
    previous = lower
    for index in range(1, size):
        value = input_list[index]
        if value == previous:
            continue
        bucket = (value - lower) >> shift
        if bucket != current_bucket:
            directory[current_bucket] = _certify_bucket(values, positions, index)
            current_bucket = bucket
            values, positions = [], []
        values.append(value)
        positions.append(index)
        previous = value
    directory[current_bucket] = _certify_bucket(values, positions, size)

    def lookup(target: int) -> int | None:
        if target < lower or target > upper:
            return None
        entry = directory[(target - lower) >> shift]
        if entry is None:
            return None
        first, last, step, mask, first_indices, start, stop = entry
        if target < first or target > last:
            return None
        if first == last:
            return start
        offset = target - first
        if step:
            rank, remainder = divmod(offset, step)
            if remainder:
                return None
            return first_indices[rank] if first_indices else start + rank
        if mask:
            bit = 1 << offset
            if not mask & bit:
                return None
            rank = (mask & (bit - 1)).bit_count()
            return first_indices[rank]
        index = bisect_left(input_list, target, start, stop)
        return index if index < stop and input_list[index] == target else None

    return lookup
