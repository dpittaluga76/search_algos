"""Quiet search functions with explicit, consistent result contracts.

Index searches return the first matching index, or ``None``. Except for
``linear_search``, they require an ascending sorted sequence. Set lookup returns
a Boolean and also accepts unsorted input. Sorting and input validation are left
to callers so they do not become part of the measured lookup cost.
"""

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from typing import TypeVar


T = TypeVar("T")


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


def binary_search(input_list: Sequence[T], lookup_value: T) -> int | None:
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


def binary_search_std_lib(input_list: Sequence[T], lookup_value: T) -> int | None:
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
    input_list: Sequence[T], lookup_value: T, left: int, right: int
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
    input_list: Sequence[T],
    lookup_value: T,
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
    if not isinstance(left, int) or not isinstance(right, int):
        raise TypeError("search bounds must be integers")
    if not 0 <= left <= len(input_list) or not -1 <= right < len(input_list):
        raise ValueError("search bounds must lie within the sequence")
    return _binary_search_recursive(input_list, lookup_value, left, right)


def interpolation_search(
    input_list: Sequence[int | float], lookup_value: int | float
) -> int | None:
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


def find_by_sets(input_list: Iterable[T], lookup_value: T) -> bool:
    """Return membership as a Boolean, building a set for this call.

    Items must be hashable. For repeated lookups, construct a set once and use
    ``target in prepared_set``; the benchmark measures that setup separately.

    >>> find_by_sets([0, 5, 7, 10, 15], 5)
    True
    >>> find_by_sets([0, 5, 7, 10, 15], 6)
    False
    """
    return lookup_value in set(input_list)
