"""Search sorted sequences in spawned processes, returning global indices.

Process startup, serialization, result collection, and shutdown happen inside
each call. Batch queries share one pool, but pools are not reused between calls.
Custom search functions must be importable, pickleable functions that return
the first matching local index, or ``None``.
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
import os
import sys
from typing import Any, Callable, Iterable, Sequence

from .algorithms import binary_search


SearchFunction = Callable[[Sequence[Any], Any], int | None]


def effective_worker_count(size: int, workers: int | None = None) -> int:
    """Validate requested workers and cap them to the available input.

    Windows' executor supports at most 61 workers. An empty input needs zero
    workers, but an explicitly invalid worker count still raises ``ValueError``.
    """
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("size must be a nonnegative integer")
    if workers is not None and (
        isinstance(workers, bool) or not isinstance(workers, int) or workers < 1
    ):
        raise ValueError("workers must be a positive integer")
    requested = workers if workers is not None else (os.cpu_count() or 1)
    if sys.platform == "win32":
        requested = min(requested, 61)
    return min(size, requested)


def chunk_ranges(size: int, workers: int | None = None) -> list[tuple[int, int]]:
    """Return balanced, nonempty half-open ranges covering every element.

    >>> chunk_ranges(10, 4)
    [(0, 3), (3, 6), (6, 8), (8, 10)]
    >>> chunk_ranges(2, 8)
    [(0, 1), (1, 2)]
    >>> chunk_ranges(0, 2)
    []
    """
    count = effective_worker_count(size, workers)
    if count == 0:
        return []
    quotient, remainder = divmod(size, count)
    ranges = []
    start = 0
    for worker in range(count):
        stop = start + quotient + (worker < remainder)
        ranges.append((start, stop))
        start = stop
    return ranges


def _search_chunk(
    values: Sequence[Any],
    targets: list[Any],
    offset: int,
    search_func: SearchFunction,
) -> list[int | None]:
    results = []
    for target in targets:
        index = search_func(values, target)
        if index is not None:
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < len(values)
                or values[index] != target
            ):
                raise ValueError("search function must return a matching index or None")
            index += offset
        results.append(index)
    return results


def parallel_search_many(
    input_list: Sequence[Any],
    lookup_values: Iterable[Any],
    workers: int | None = None,
    search_func: SearchFunction = binary_search,
) -> list[int | None]:
    """Return first matching global indices for a batch of queries.

    Input must be sorted ascending for the default binary search. Exceptions
    raised by a worker propagate to the caller. An abruptly terminated worker
    raises ``concurrent.futures.process.BrokenProcessPool``. Executor shutdown
    joins the children before this function returns or propagates an error.

    Because processes use the ``spawn`` start method on every platform, scripts
    calling this function must put their entry point under a ``__main__`` guard.
    """
    ranges = chunk_ranges(len(input_list), workers)
    targets = list(lookup_values)
    results: list[int | None] = [None] * len(targets)
    if not ranges or not targets:
        return results

    with ProcessPoolExecutor(
        max_workers=len(ranges), mp_context=get_context("spawn")
    ) as executor:
        futures = [
            executor.submit(
                _search_chunk, input_list[start:stop], targets, start, search_func
            )
            for start, stop in ranges
        ]
        for future in as_completed(futures):
            for position, index in enumerate(future.result()):
                current = results[position]
                if index is not None and (current is None or index < current):
                    results[position] = index
    return results


def parallel_search(
    input_list: Sequence[Any],
    lookup_value: Any,
    workers: int | None = None,
    search_func: SearchFunction = binary_search,
) -> int | None:
    """Return the first matching global index, or ``None`` when absent."""
    return parallel_search_many(input_list, [lookup_value], workers, search_func)[0]


def multiproc_test(
    func: SearchFunction,
    lst_size: int,
    seq: Sequence[Any],
    tgt: Any,
    cpu_cnt: int,
) -> int | None:
    """Compatibility entry point returning a global index instead of printing.

    New callers should use :func:`parallel_search`, which derives the size from
    its input. The legacy size argument must agree with the actual sequence.
    """
    effective_worker_count(lst_size, cpu_cnt)
    if lst_size != len(seq):
        raise ValueError("lst_size must equal the sequence length")
    return parallel_search(seq, tgt, workers=cpu_cnt, search_func=func)
