"""Additional search strategies adapted from TheAlgorithms/Python.

Sources: searches/ at commit 6e03a48579ca212a08b36be00378f887dc41a003.
Copyright (c) 2016-2022 TheAlgorithms and contributors. MIT license; see LICENSE.

Index searches return the first match or None. The slicing binary search returns
Boolean membership. Caller-owned inputs are never modified. These alternatives
are separate from the original algorithms and included in the default benchmarks.
"""

from bisect import bisect_left
from collections.abc import Callable, Iterable, Sequence

from .algorithms import C, T

# Resume long recursive scans in another batch without changing their strategy
# or Python's process-wide recursion limit.
_RECURSION_BATCH = 64
_TERNARY_LINEAR_THRESHOLD = 10


def fibonacci_search(input_list: Sequence[C], lookup_value: C) -> int | None:
    """Fibonacci array search (Fibonaccian search) returning the first match.

    Input must be sorted ascending.

    Fibonacci numbers are computed locally on each call, without a shared cache.
    Equality follows the left branch so duplicates retain their first index.

    >>> fibonacci_search([1, 2, 2, 2, 3], 2)
    1
    >>> fibonacci_search([1, 3, 5], 4)
    >>> fibonacci_search([], 1)
    """
    size = len(input_list)
    smaller, previous, current = 0, 1, 1
    while current < size:
        smaller, previous, current = previous, current, previous + current
    offset = -1
    while current > 1:
        index = min(offset + smaller, size - 1)
        if input_list[index] < lookup_value:
            current, previous = previous, smaller
            smaller = current - previous
            offset = index
        else:
            current, previous = smaller, previous - smaller
            smaller = current - previous
    index = offset + 1
    if index < size and input_list[index] == lookup_value:
        return index
    return None


def ternary_search(input_list: Sequence[C], lookup_value: C) -> int | None:
    """Ternary array search with a small linear finish, returning the first match.

    This is sorted-array value lookup, not optimization of a unimodal function.

    Input must be ascending. Probe positions remain in the candidate interval
    until earlier duplicates have been ruled out.

    >>> ternary_search([0] + [1] * 18 + [2], 1)
    1
    >>> ternary_search([1, 3, 5], 4)
    """
    left, right = 0, len(input_list)
    while right - left >= _TERNARY_LINEAR_THRESHOLD:
        third = (right - left) // 3
        first, second = left + third, right - third
        if not input_list[first] < lookup_value:
            right = first + 1
        elif not input_list[second] < lookup_value:
            left, right = first + 1, second + 1
        else:
            left = second + 1
    for index in range(left, right):
        if input_list[index] == lookup_value:
            return index
    return None


def _ternary_search_recursive(
    input_list: Sequence[C], lookup_value: C, left: int, right: int
) -> int | None:
    if right - left < _TERNARY_LINEAR_THRESHOLD:
        for index in range(left, right):
            if input_list[index] == lookup_value:
                return index
        return None
    third = (right - left) // 3
    first, second = left + third, right - third
    if not input_list[first] < lookup_value:
        return _ternary_search_recursive(input_list, lookup_value, left, first + 1)
    if not input_list[second] < lookup_value:
        return _ternary_search_recursive(input_list, lookup_value, first + 1, second + 1)
    return _ternary_search_recursive(input_list, lookup_value, second + 1, right)


def ternary_search_by_recursion(input_list: Sequence[C], lookup_value: C) -> int | None:
    """Recursive ternary array search with a small linear finish.

    Input must be ascending. Recursion depth is logarithmic in the input size.

    >>> ternary_search_by_recursion([0] + [1] * 18 + [2], 1)
    1
    >>> ternary_search_by_recursion([], 1)
    """
    return _ternary_search_recursive(input_list, lookup_value, 0, len(input_list))


def double_linear_search(input_list: Sequence[T], lookup_value: T) -> int | None:
    """Double-ended linear search retaining the first occurrence.

    Sorting is unnecessary. First-index semantics mean that a right-side hit
    cannot end the search immediately when earlier duplicates may exist.

    >>> double_linear_search([9, 2, 7, 2], 2)
    1
    >>> double_linear_search([1, 2, 3], 4)
    """
    left, right = 0, len(input_list) - 1
    result = None
    while left <= right:
        if input_list[left] == lookup_value:
            return left
        if input_list[right] == lookup_value:
            result = right
        left += 1
        right -= 1
    return result


def _double_linear_recursive(
    input_list: Sequence[T],
    lookup_value: T,
    left: int,
    right: int,
    result: int | None,
    remaining: int,
) -> tuple[int | None, int | None]:
    if left > right:
        return result, None
    if remaining == 0:
        return result, left
    if input_list[left] == lookup_value:
        return left, None
    if input_list[right] == lookup_value:
        result = right
    return _double_linear_recursive(
        input_list, lookup_value, left + 1, right - 1, result, remaining - 1
    )


def double_linear_search_by_recursion(input_list: Sequence[T], lookup_value: T) -> int | None:
    """Recursive double-ended linear search for the first occurrence.

    Each recursive batch examines at most 64 pairs. A driver resumes the next
    batch with the same scan state, bounding stack use even for long misses.

    >>> double_linear_search_by_recursion([9, 2, 7, 2], 2)
    1
    >>> double_linear_search_by_recursion([], 1)
    """
    size = len(input_list)

    next_left: int | None = 0
    result = None
    while next_left is not None:
        result, next_left = _double_linear_recursive(
            input_list, lookup_value, next_left, size - 1 - next_left, result, _RECURSION_BATCH
        )
    return result


def build_sentinel_search(input_list: Iterable[T]) -> Callable[[T], int | None]:
    """Prepare sentinel linear search with a reusable private buffer.

    Preparation costs O(n) time and space. Each lookup appends its target as a
    sentinel and removes it in a finally block, including when equality raises.
    Values must have reflexive equality. The callable is for sequential reuse;
    it must not be called concurrently or reentered from an equality method.
    The copy is shallow, so element objects must remain unchanged during reuse.

    >>> lookup = build_sentinel_search(iter([3, 1, 3]))
    >>> lookup(3)
    0
    >>> lookup(2)
    >>> lookup(1)
    1
    """
    values = list(input_list)
    size = len(values)

    def lookup(target: T) -> int | None:
        values.append(target)
        try:
            index = 0
            while not values[index] == target:
                index += 1
            return index if index < size else None
        finally:
            values.pop()

    return lookup


def sentinel_linear_search(input_list: Iterable[T], lookup_value: T) -> int | None:
    """Sentinel linear search for the first match using a fresh private buffer.

    Sorting is unnecessary; equality must be reflexive. Use build_sentinel_search
    to amortize the copy over repeated lookups. Caller-owned input is unchanged.

    >>> sentinel_linear_search((3, 1, 3), 3)
    0
    >>> sentinel_linear_search([1, 2, 3], 4)
    """
    return build_sentinel_search(input_list)(lookup_value)


def _interpolation_recursive(
    input_list: Sequence[int | float],
    lookup_value: float,
    low: int,
    high: int,
    result: int | None,
    remaining: int,
) -> tuple[int | None, tuple[int, int] | None]:
    if low > high or not input_list[low] <= lookup_value <= input_list[high]:
        return result, None
    lower, upper = input_list[low], input_list[high]
    if lower == lookup_value:
        return low, None
    if remaining == 0:
        return result, (low, high)
    try:
        offset = int((lookup_value - lower) * (high - low) // (upper - lower))
    except (OverflowError, ValueError, ZeroDivisionError):
        index = bisect_left(input_list, lookup_value, low, high + 1)
        if index <= high and input_list[index] == lookup_value:
            return index, None
        return result, None
    index = min(high, max(low, low + offset))
    value = input_list[index]
    if value < lookup_value:
        return _interpolation_recursive(
            input_list, lookup_value, index + 1, high, result, remaining - 1
        )
    if value == lookup_value:
        result = index
    return _interpolation_recursive(input_list, lookup_value, low, index - 1, result, remaining - 1)


def interpolation_search_by_recursion(
    input_list: Sequence[int | float], lookup_value: float
) -> int | None:
    """Recursive interpolation search with numeric safeguards and first-index results.

    Batches of at most 64 probes bound stack use; subsequent batches continue
    interpolating, preserving the O(n) worst case. Only unsafe numeric arithmetic
    uses bounded bisection, as in the original interpolation APIs.

    >>> interpolation_search_by_recursion([0, 1, 1, 1, 2], 1)
    1
    >>> interpolation_search_by_recursion([1, 3, 5], 4)
    >>> interpolation_search_by_recursion([], 1)
    """

    bounds: tuple[int, int] | None = (0, len(input_list) - 1)
    result = None
    while bounds is not None:
        result, bounds = _interpolation_recursive(
            input_list, lookup_value, *bounds, result, _RECURSION_BATCH
        )
    return result


def binary_search_slicing(input_list: Sequence[C], lookup_value: C) -> bool:
    """Recursive binary membership search using slices of ascending input.

    List/tuple slicing copies elements, costing O(n) time and extra space in
    the worst case despite logarithmic comparison count and recursion depth.

    >>> binary_search_slicing([1, 3, 3, 8], 3)
    True
    >>> binary_search_slicing([1, 3, 3, 8], 4)
    False
    >>> binary_search_slicing([], 1)
    False
    """
    if len(input_list) == 0:
        return False
    midpoint = len(input_list) // 2
    if input_list[midpoint] == lookup_value:
        return True
    if lookup_value < input_list[midpoint]:
        return binary_search_slicing(input_list[:midpoint], lookup_value)
    return binary_search_slicing(input_list[midpoint + 1 :], lookup_value)
