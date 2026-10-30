"""Sprint candidates: skip duplicate runs while preparing first-index lookups.

These are separate experiments. Sorted integer input and unchanged data during
use are preconditions, as with the other prepared factories.
"""

from bisect import bisect_right
from collections.abc import Callable, Sequence

from search_algos.algorithms import build_radix_index
from search_algos.prepared import (
    build_first_index_reversed,
    build_guarded_index,
    build_neighbor_index,
)


def build_run_index(input_list: Sequence[int]) -> Callable[[int], int | None]:
    """Index one entry per duplicate run using bisection to skip its remainder.

    Setup skips at most max(128, 2*n/bit_length(n)) runs before switching to the
    existing reverse-iterator dictionary builder. This bounds bisection work
    asymptotically by O(n) comparisons, including misleading duplicate samples.
    Long runs need only O(u log n) comparisons and O(u) storage for u distinct
    keys. This can cost less than visiting n elements when runs are long.
    Dictionary lookup has expected constant cost under ordinary integer hashing;
    arbitrary-size arithmetic/hash costs and adversarial collisions still apply.
    """
    first: dict[int, int] = {}
    size = len(input_list)
    run_limit = max(128, 2 * size // max(1, size.bit_length()))
    position = 0
    while position < size:
        value = input_list[position]
        first[value] = position
        position = bisect_right(input_list, value, position + 1, size)
        if len(first) >= run_limit and position < size:
            return build_first_index_reversed(input_list).get
    return first.get


def build_run_adaptive_index(input_list: Sequence[int]) -> Callable[[int], int | None]:
    """Choose run indexing for duplicate-rich samples, exact alternatives otherwise.

    Sampling changes only preparation strategy, never result correctness.
    """
    size = len(input_list)
    if not size:
        return lambda target: None
    lower, upper = input_list[0], input_list[-1]
    if lower == upper:
        return lambda target: 0 if target == lower else None
    last, span = size - 1, upper - lower
    positions = sorted({max(1, last * index // 16) for index in range(1, 17)})
    duplicates = sum(input_list[position] == input_list[position - 1] for position in positions)
    if duplicates * 4 >= len(positions) * 3:
        return build_run_index(input_list)
    max_error = max(
        abs((input_list[position] - lower) * last // span - position) for position in positions
    )
    if max_error <= 1:
        return build_neighbor_index(input_list)
    if max_error * 4 > last:
        return build_guarded_index(input_list)
    return build_radix_index(input_list)
