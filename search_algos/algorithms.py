"""Quiet search functions with explicit, consistent result contracts.

Index searches return the first matching index, or ``None``. Binary,
interpolation, exponential, jump, and prepared radix searches require ascending sorted input.
Linear search and the hash-based helpers also accept unsorted input. Sorting and
input validation are left to callers so they do not become part of lookup cost.
"""

from bisect import bisect_left
from collections.abc import Callable, Hashable, Iterable, Sequence
from math import isqrt
from typing import Any, Protocol, TypeVar

T = TypeVar("T")
H = TypeVar("H", bound=Hashable)


class Comparable(Protocol):
    """Values supporting the ordering operation used by sorted searches."""

    def __lt__(self, other: Any, /) -> bool: ...


C = TypeVar("C", bound=Comparable)


def linear_search(input_list: Iterable[T], lookup_value: T) -> int | None:
    """Return the first matching index; input need not be sorted.

    >>> linear_search([0, 15, 17, 20, 25], 20)
    3
    >>> linear_search([0, 11, 22, 30, 40], 6)
    >>> linear_search([5, 2, 5], 5)
    0
    """
    for index, item in enumerate(input_list):
        if item == lookup_value:
            return index
    return None


def binary_search(input_list: Sequence[C], lookup_value: C) -> int | None:
    """Return the first matching index in an ascending sorted sequence.

    >>> binary_search([0, 3, 5, 33, 44], 0)
    0
    >>> binary_search([0, 1, 2, 3, 4], 6)
    >>> binary_search([1, 2, 2, 2, 3], 2)
    1
    """
    left, right = 0, len(input_list)
    while left < right:
        midpoint = left + (right - left) // 2
        if input_list[midpoint] < lookup_value:
            left = midpoint + 1
        else:
            right = midpoint
    if left < len(input_list) and input_list[left] == lookup_value:
        return left
    return None


def binary_search_std_lib(input_list: Sequence[C], lookup_value: C) -> int | None:
    """Find the first match in an ascending sorted sequence using ``bisect``.

    >>> binary_search_std_lib([0, 5, 7, 10, 15], 0)
    0
    >>> binary_search_std_lib([0, 5, 7, 10, 15], 15)
    4
    >>> binary_search_std_lib([0, 5, 7, 10, 15], 5)
    1
    >>> binary_search_std_lib([0, 5, 7, 10, 15], 6)
    """
    index = bisect_left(input_list, lookup_value)
    if index < len(input_list) and input_list[index] == lookup_value:
        return index
    return None


def _binary_search_recursive(
    input_list: Sequence[C], lookup_value: C, left: int, right: int
) -> int | None:
    if left > right:
        return None
    midpoint = left + (right - left) // 2
    if input_list[midpoint] < lookup_value:
        return _binary_search_recursive(input_list, lookup_value, midpoint + 1, right)
    earlier = _binary_search_recursive(input_list, lookup_value, left, midpoint - 1)
    if earlier is not None:
        return earlier
    return midpoint if input_list[midpoint] == lookup_value else None


def binary_search_by_recursion(
    input_list: Sequence[C],
    lookup_value: C,
    left: int = 0,
    right: int | None = None,
) -> int | None:
    """Return the first matching index using a private recursive helper.

    Normally pass only the sequence and target. Optional legacy bounds are
    inclusive; the result is the first match within those bounds. Invalid bounds
    raise ``ValueError`` instead of indexing outside the sequence. An empty
    search interval returns ``None``.

    >>> binary_search_by_recursion([0, 5, 7, 10, 15], 0)
    0
    >>> binary_search_by_recursion([0, 5, 7, 10, 15], 6)
    >>> binary_search_by_recursion([1, 2, 2, 2, 3], 2)
    1
    >>> binary_search_by_recursion([], 9)
    """
    if right is None:
        right = len(input_list) - 1
    if (
        isinstance(left, bool)
        or isinstance(right, bool)
        or not isinstance(left, int)
        or not isinstance(right, int)
    ):
        raise TypeError("search bounds must be integers")
    if not 0 <= left <= len(input_list) or not -1 <= right < len(input_list):
        raise ValueError("search bounds must lie within the sequence")
    return _binary_search_recursive(input_list, lookup_value, left, right)


def interpolation_search(input_list: Sequence[int | float], lookup_value: float) -> int | None:
    """Return the first match in ascending sorted, finite numeric input.

    Integers use exact arithmetic, including integers larger than a float can
    represent. Finite floats are supported; if probe arithmetic overflows, a
    binary lookup provides a safe fallback. As with other sorted searches, the
    caller is responsible for the input preconditions.

    >>> interpolation_search([0, 5, 7, 10, 15], 0)
    0
    >>> interpolation_search([0, 5, 7, 10, 15], 6)
    >>> interpolation_search([5, 5, 5], 5)
    0
    >>> interpolation_search([5], 6)
    """
    low, high = 0, len(input_list) - 1
    result = None
    while low <= high and input_list[low] <= lookup_value <= input_list[high]:
        lower, upper = input_list[low], input_list[high]
        # This handles singletons, constant intervals, and duplicate runs.
        if lower == lookup_value:
            return low
        if lower == upper:
            break
        try:
            offset = int((lookup_value - lower) * (high - low) // (upper - lower))
        except (OverflowError, ValueError):
            return binary_search_std_lib(input_list, lookup_value)
        # Floating point rounding must not produce an out-of-range probe.
        index = min(high, max(low, low + offset))
        if input_list[index] < lookup_value:
            low = index + 1
        else:
            if input_list[index] == lookup_value:
                result = index
            high = index - 1
    return result


def interpolation_search_hybrid(
    input_list: Sequence[int | float], lookup_value: float
) -> int | None:
    """Interpolate briefly, then use binary search if progress is too slow.

    At most ``len(input_list).bit_length()`` interpolation probes are made.
    The binary fallback searches the remaining interval, preserving the first
    match even when duplicate values precede an already-discovered match.
    Input must be ascending and contain finite numeric values.

    >>> interpolation_search_hybrid([1, 2, 3, 4, 10**12], 4)
    3
    >>> interpolation_search_hybrid([1, 2, 2, 2, 10**12], 2)
    1
    >>> interpolation_search_hybrid([], 4)
    """
    low, high = 0, len(input_list) - 1
    remaining_probes = len(input_list).bit_length()
    result = None
    while low <= high and input_list[low] <= lookup_value <= input_list[high]:
        lower, upper = input_list[low], input_list[high]
        if lower == lookup_value:
            return low
        if lower == upper:
            break
        if remaining_probes == 0:
            break
        remaining_probes -= 1
        try:
            offset = int((lookup_value - lower) * (high - low) // (upper - lower))
        except (OverflowError, ValueError):
            break
        index = min(high, max(low, low + offset))
        if input_list[index] < lookup_value:
            low = index + 1
        else:
            if input_list[index] == lookup_value:
                result = index
            high = index - 1
    if low <= high:
        index = bisect_left(input_list, lookup_value, low, high + 1)
        if index <= high and input_list[index] == lookup_value:
            return index
    return result


def exponential_search(input_list: Sequence[C], lookup_value: C) -> int | None:
    """Find the first match by galloping to a bound, then binary searching.

    Input must be sorted ascending. The galloping phase doubles its bound until
    it reaches or passes the target; no sequence slices are created.

    >>> exponential_search([1, 3, 3, 8, 20], 3)
    1
    >>> exponential_search([1, 3, 8], 9)
    >>> exponential_search([], 1)
    """
    size = len(input_list)
    if size == 0:
        return None
    if input_list[0] == lookup_value:
        return 0
    bound = 1
    while bound < size and input_list[bound] < lookup_value:
        bound *= 2
    index = bisect_left(input_list, lookup_value, bound // 2, min(bound + 1, size))
    if index < size and input_list[index] == lookup_value:
        return index
    return None


def jump_search(input_list: Sequence[C], lookup_value: C) -> int | None:
    """Find the first match using square-root blocks and a linear block scan.

    Input must be sorted ascending.

    >>> jump_search([1, 2, 2, 2, 3, 4], 2)
    1
    >>> jump_search([1, 2, 3], 4)
    >>> jump_search([], 4)
    """
    size = len(input_list)
    if size == 0:
        return None
    step = max(1, isqrt(size))
    start, stop = 0, min(step, size)
    while input_list[stop - 1] < lookup_value:
        start = stop
        if start >= size:
            return None
        stop = min(stop + step, size)
    for index in range(start, stop):
        current = input_list[index]
        if current == lookup_value:
            return index
        if lookup_value < current:
            break
    return None


def build_radix_index(input_list: Sequence[int], *, bits: int = 12) -> Callable[[int], int | None]:
    """Prepare a radix directory for repeated first-index integer lookups.

    Input must be sorted ascending and both values and lookup targets must be
    integers. These are preconditions: construction does not scan, validate, or
    copy the sequence. The returned callable retains the sequence; do not mutate
    it until all lookups are finished. Rebuild the index after changing input.

    ``bits`` must be an integer from 0 through 12, excluding Boolean values.
    At most ``2**bits`` buckets are created (4,096 by default); zero bits uses
    one bucket. Lower-bound directory entries keep duplicate runs together.
    Each lookup rejects targets outside the value range, then uses ``bisect``
    inside the target's bucket and verifies equality before returning an index.

    Construction uses O(B log n) sequence accesses and O(B) extra storage for B
    buckets. Lookup uses O(log(m + 1)) accesses for a bucket of m values, O(log n)
    in the worst case. Outliers or skewed values can leave most data in one
    bucket, and small query batches may not repay the construction cost.

    >>> lookup = build_radix_index([-5, 1, 1, 8])
    >>> lookup(1)
    1
    >>> lookup(-5)
    0
    >>> lookup(3)
    >>> build_radix_index([])(1)
    """
    if type(bits) is not int or not 0 <= bits <= 12:
        raise ValueError("bits must be an integer between 0 and 12")
    if not input_list:
        return lambda target: None

    lower, upper = input_list[0], input_list[-1]
    shift = max(0, (upper - lower).bit_length() - bits)
    bucket_count = ((upper - lower) >> shift) + 1
    offsets = [
        bisect_left(input_list, lower + (bucket << shift)) for bucket in range(bucket_count + 1)
    ]

    def lookup(target: int) -> int | None:
        if target < lower or target > upper:
            return None
        bucket = (target - lower) >> shift
        stop = offsets[bucket + 1]
        index = bisect_left(input_list, target, offsets[bucket], stop)
        return index if index < stop and input_list[index] == target else None

    return lookup


def build_first_index(input_list: Iterable[H]) -> dict[H, int]:
    """Build a hash index mapping each value to its first input position.

    Input need not be sorted, but values must be hashable. Construct this once
    and call ``index.get(target)`` for repeated first-index lookups.

    >>> build_first_index([3, 1, 3, 2, 1])
    {3: 0, 1: 1, 2: 3}
    >>> build_first_index([])
    {}
    """
    result: dict[H, int] = {}
    for index, value in enumerate(input_list):
        result.setdefault(value, index)
    return result


def find_by_dict(input_list: Iterable[H], lookup_value: H) -> int | None:
    """Return the first match, building a hash index for this call.

    >>> find_by_dict([3, 1, 3, 2, 1], 1)
    1
    >>> find_by_dict([3, 1], 9)
    """
    return build_first_index(input_list).get(lookup_value)


def find_by_sets(input_list: Iterable[H], lookup_value: H) -> bool:
    """Return membership as a Boolean, building a set for this call.

    Items must be hashable. For repeated lookups, construct a set once and use
    ``target in prepared_set``; the benchmark measures that setup separately.

    >>> find_by_sets([0, 5, 7, 10, 15], 5)
    True
    >>> find_by_sets([0, 5, 7, 10, 15], 6)
    False
    """
    return lookup_value in set(input_list)
