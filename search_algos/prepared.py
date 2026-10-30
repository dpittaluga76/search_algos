"""Project hybrids and prepared variants of established lookup techniques.

The numeric factories borrow ascending integer sequences. Integer targets and
unchanged input during lookup are preconditions; no full validation scan or
input copy is performed. Sampling in the adaptive factory chooses a strategy,
not an approximation: every selected strategy returns an exact first index.
"""

from bisect import bisect_left
from collections.abc import Callable, Hashable, Iterable, Sequence
from typing import TypeVar

from .algorithms import build_radix_index

H = TypeVar("H", bound=Hashable)


def build_neighbor_index(input_list: Sequence[int]) -> Callable[[int], int | None]:
    """Prepared interpolation prediction, neighbor checks, and binary fallback.

    This is a project hybrid of established techniques, not a nearest-neighbor
    retrieval algorithm; it answers exact first-index queries.

    Input must remain sorted, integer-valued, and unchanged during use. Setup
    needs constant sequence accesses and storage. A probe and adjacent checks
    can resolve regular data immediately; otherwise a bounded ``bisect_left``
    preserves first-index semantics, including long duplicate runs. Worst-case
    lookup uses O(log n) sequence accesses. Integer arithmetic costs depend on
    the size of the integers.

    >>> lookup = build_neighbor_index([-4, 0, 0, 8])
    >>> lookup(0)
    1
    >>> lookup(3)
    >>> build_neighbor_index([])(2)
    """
    size = len(input_list)
    if size == 0:
        return lambda target: None
    lower, upper = input_list[0], input_list[-1]
    span, last = upper - lower, size - 1
    if span == 0:
        return lambda target: 0 if target == lower else None

    def lookup(target: int) -> int | None:
        if target < lower or target > upper:
            return None
        if target == lower:
            return 0
        position = (target - lower) * last // span
        value = input_list[position]
        if value == target:
            if position == 0 or not input_list[position - 1] == target:
                return position
            return bisect_left(input_list, target, 0, position)
        if value < target:
            neighbor = position + 1
            if neighbor >= size:
                return None
            next_value = input_list[neighbor]
            if next_value == target:
                return neighbor
            if target < next_value:
                return None
            left, right = neighbor + 1, size
        else:
            neighbor = position - 1
            if neighbor < 0:
                return None
            previous_value = input_list[neighbor]
            if previous_value < target:
                return None
            if previous_value == target:
                if neighbor == 0 or not input_list[neighbor - 1] == target:
                    return neighbor
                return bisect_left(input_list, target, 0, neighbor)
            left, right = 0, neighbor
        index = bisect_left(input_list, target, left, right)
        return index if index < right and input_list[index] == target else None

    return lookup


def build_first_index_reversed(input_list: Iterable[H]) -> dict[H, int]:
    """Build a first-occurrence hash index using reverse-traversal overwrites.

    Values must be hashable; sorting is unnecessary. A sequence is traversed
    without copying. Other iterables are first materialized as a tuple, needing
    temporary O(n) storage in addition to the O(u) dictionary for u unique keys.
    Construction uses O(n) expected hash operations.

    Values map to their first indices, but dictionary iteration order follows
    reverse last-occurrence order. Equal keys retain the key object from the
    last occurrence in the input. These intentionally differ from
    ``build_first_index``, which preserves first-occurrence order and objects.

    >>> index = build_first_index_reversed(["a", "b", "a", "c", "b"])
    >>> list(index.items())
    [('b', 1), ('c', 3), ('a', 0)]
    >>> build_first_index_reversed(iter([3, 1, 3])).get(3)
    0
    """
    values: Sequence[H] = input_list if isinstance(input_list, Sequence) else tuple(input_list)
    return dict(zip(reversed(values), range(len(values) - 1, -1, -1)))


def build_guarded_index(input_list: Sequence[int]) -> Callable[[int], int | None]:
    """Binary search with cached endpoint guards, a prepared project wrapper.

    Input and targets must be integers; input must stay sorted and unchanged.
    Setup uses constant sequence accesses and storage. In-range queries use
    O(log n) sequence accesses and return the first matching index or ``None``.

    >>> lookup = build_guarded_index([-4, 0, 0, 8])
    >>> lookup(0)
    1
    >>> lookup(9)
    """
    size = len(input_list)
    if size == 0:
        return lambda target: None
    lower, upper = input_list[0], input_list[-1]

    def lookup(target: int) -> int | None:
        if target < lower or target > upper:
            return None
        index = bisect_left(input_list, target)
        return index if index < size and input_list[index] == target else None

    return lookup


def build_adaptive_index(input_list: Sequence[int]) -> Callable[[int], int | None]:
    """Heuristic selection among prepared lookup strategies, a project hybrid.

    At most 16 fixed positions are sampled. This selects an implementation
    rather than constructing an adaptive radix tree or fitting a learned model.

    Sorted integers and unchanged input during use are preconditions. Empty and
    constant inputs have direct-return fast paths. Other inputs sample positions
    ``max(1, (n - 1) * i // 16)`` for i=1..16, deduplicating positions on small
    inputs. Each sampled value is compared with its immediate predecessor.

    If more than half these adjacent pairs are equal, build a reverse dictionary
    and return its bound ``get`` method. Otherwise measure the largest difference
    between a sampled position and its endpoint-based interpolation prediction:
    error <= 1 chooses neighbor search; error * 4 > n - 1 chooses guarded bisect;
    the remaining inputs use the existing radix index. Sampling affects speed
    only; even misleading samples cannot change the exact result contract.

    Sampling needs constant sequence accesses. Subsequent setup and memory costs
    depend on the selected strategy: the dictionary branch scans the input and
    keeps one entry per distinct value, while radix builds its bounded directory.
    Selection is a fixed heuristic, not a guarantee of the fastest strategy.

    >>> lookup = build_adaptive_index([0, 2, 4, 6])
    >>> lookup(4)
    2
    >>> lookup(3)
    """
    size = len(input_list)
    if size == 0:
        return lambda target: None
    lower, upper = input_list[0], input_list[-1]
    span, last = upper - lower, size - 1
    if span == 0:
        return lambda target: 0 if target == lower else None
    positions = sorted({max(1, last * i // 16) for i in range(1, 17)})
    duplicates = sum(input_list[position] == input_list[position - 1] for position in positions)
    if duplicates * 2 > len(positions):
        return build_first_index_reversed(input_list).get
    max_error = max(
        abs((input_list[position] - lower) * last // span - position) for position in positions
    )
    if max_error <= 1:
        return build_neighbor_index(input_list)
    if max_error * 4 > last:
        return build_guarded_index(input_list)
    return build_radix_index(input_list)
