"""Adaptive stride/run/radix lookup, a project hybrid named landmark_index.

This experimental hybrid preserves every existing algorithm. Sorted integer
input, integer targets, and unchanged input during reuse are preconditions.
Sampling selects a strategy; it never certifies membership or absence.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence


def _stride_lookup(
    values: Sequence[int], lower: int, upper: int, step: int
) -> Callable[[int], int | None]:
    size = len(values)

    def lookup(target: int) -> int | None:
        if target < lower or target > upper:
            return None
        # Exact endpoint divisibility bounds this prediction even if the
        # interior is irregular. It does not establish that a key exists.
        position = (target - lower) // step
        value = values[position]
        if value == target:
            if position == 0 or values[position - 1] < target:
                return position
            return bisect_left(values, target, 0, position)
        if value < target:
            if position + 1 == size or values[position + 1] > target:
                return None
            left, right = position + 1, size
        else:
            if position == 0 or values[position - 1] < target:
                return None
            left, right = 0, position
        index = bisect_left(values, target, left, right)
        return index if index < right and values[index] == target else None

    return lookup


def _directory_lookup(values: Sequence[int], lower: int, upper: int) -> Callable[[int], int | None]:
    shift = max(0, (upper - lower).bit_length() - 10)
    count = ((upper - lower) >> shift) + 1
    offsets = [bisect_left(values, lower + (bucket << shift)) for bucket in range(count + 1)]

    def lookup(target: int, _search: Callable[..., int] = bisect_left) -> int | None:
        if target < lower or target > upper:
            return None
        bucket = (target - lower) >> shift
        index = _search(values, target, offsets[bucket], offsets[bucket + 1])
        # An interior stop is a valid index holding a value above this bucket.
        # At the final stop, target <= upper ensures bisect returns index < n.
        return index if values[index] == target else None

    return lookup


def _run_lookup(values: Sequence[int]) -> Callable[[int], int | None] | None:
    size = len(values)
    limit = max(128, 2 * size // size.bit_length())
    first: dict[int, int] = {}
    position = 0
    while position < size:
        value = values[position]
        first[value] = position
        position = bisect_right(values, value, position + 1, size)
        if len(first) >= limit and position < size:
            # Misleading samples affect preparation cost, not correctness.
            # Discard the partial map: it cannot answer arbitrary queries.
            return None
    return first.get


def build_landmark_index(values: Sequence[int]) -> Callable[[int], int | None]:
    """Adaptive stride/run/radix lookup hybrid returning exact first indices.

    Landmark is this project's identifier for the combination, rather than a
    canonical name claimed for an algorithm in the literature.

    Input must be sorted ascending, integer-valued, and unchanged during reuse;
    targets must be integers. These preconditions are not validated by a scan.
    Empty and constant sequences have constant-cost direct lookup paths.

    At most 16 adjacent pairs are sampled. If at least three quarters are equal,
    preparation records each distinct key's first index and skips its duplicate
    run with ``bisect_right``. After max(128, 2*n // n.bit_length()) distinct
    runs, an incomplete map is discarded and preparation switches to a radix
    directory. This caps the asymptotic number of run-search comparisons at O(n).

    Otherwise, exact divisibility of the endpoint span by n - 1 selects a stride
    prediction. Every query verifies equality and the preceding value, or an
    immediate absence bracket, before returning. Inaccurate predictions use
    bounded ``bisect_left``; divisible endpoints never certify interior spacing.
    Remaining inputs use at most 1,024 radix buckets and bounded bisection.

    With fixed-width keys, stride preparation uses O(1) work/storage and queries
    use O(log n) comparisons in the worst case. The run path uses O(u log n)
    comparisons and O(u) storage for u distinct keys until its run budget; lookup
    has expected O(1) hash-table cost. An aborted run path uses O(n + B log n)
    comparisons and O(L + B) peak storage for its run limit L and B<=1024.
    Ordinary directory preparation uses O(B log n) comparisons/O(B) storage;
    lookup uses O(log(m + 1)) comparisons in a bucket with m values. Arbitrarily
    large integer arithmetic and hashing add operand-size-dependent costs.

    Selection is a performance heuristic, not a fastest-strategy guarantee.
    This combines established techniques and claims no theoretical novelty.

    >>> lookup = build_landmark_index([0, 3, 6, 9])
    >>> lookup(6)
    2
    >>> lookup(7)
    >>> build_landmark_index([-2, -2, 5, 5])(5)
    2
    >>> build_landmark_index([])(3)
    """
    size = len(values)
    if not size:
        return lambda target: None
    lower, upper = values[0], values[-1]
    if lower == upper:
        return lambda target: 0 if target == lower else None
    last = size - 1
    positions = sorted({max(1, last * index // 16) for index in range(1, 17)})
    duplicates = sum(values[position] == values[position - 1] for position in positions)
    if duplicates * 4 >= len(positions) * 3:
        run_lookup = _run_lookup(values)
        if run_lookup is not None:
            return run_lookup
        return _directory_lookup(values, lower, upper)
    step, remainder = divmod(upper - lower, last)
    if step and not remainder:
        return _stride_lookup(values, lower, upper, step)
    return _directory_lookup(values, lower, upper)
