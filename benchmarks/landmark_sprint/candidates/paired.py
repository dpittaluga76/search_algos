"""Unselected paired-directory candidate for isolated sprint comparisons.

Exact first-index semantics match the production directory. This changes only
metadata layout: a bucket lookup retrieves both bounds with one subscription.
It adds O(B) tuple allocations during preparation. No baseline is replaced.
"""

from bisect import bisect_left
from collections.abc import Callable, Sequence


def build_paired_radix_index(
    values: Sequence[int], *, bits: int = 10, bind_locals: bool = False
) -> Callable[[int], int | None]:
    """Prepare paired bounds; optional default bindings are a separate variant."""
    if type(bits) is not int or not 0 <= bits <= 12:
        raise ValueError("bits must be an integer between 0 and 12")
    if not values:
        return lambda target: None
    lower, upper = values[0], values[-1]
    shift = max(0, (upper - lower).bit_length() - bits)
    count = ((upper - lower) >> shift) + 1
    offsets = [bisect_left(values, lower + (bucket << shift)) for bucket in range(count + 1)]
    pairs = tuple(zip(offsets, offsets[1:]))
    if bind_locals:

        def local_lookup(
            target: int,
            _search: Callable[..., int] = bisect_left,
            _values: Sequence[int] = values,
            _lower: int = lower,
            _upper: int = upper,
            _shift: int = shift,
            _pairs: tuple[tuple[int, int], ...] = pairs,
        ) -> int | None:
            if target < _lower or target > _upper:
                return None
            left, right = _pairs[(target - _lower) >> _shift]
            index = _search(_values, target, left, right)
            return index if _values[index] == target else None

        return local_lookup

    def lookup(target: int, _search: Callable[..., int] = bisect_left) -> int | None:
        if target < lower or target > upper:
            return None
        left, right = pairs[(target - lower) >> shift]
        index = _search(values, target, left, right)
        # At an interior stop, this valid element belongs to a later bucket
        # and cannot equal target. The global upper guard prevents index == n
        # for the last bucket, because its maximum is included in the search.
        return index if values[index] == target else None

    return lookup
