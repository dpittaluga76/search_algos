"""Routed searches with cold or explicitly reused spawned workers.

Routing requires ascending sorted input and sends each target only to the first
chunk that could contain it. This preserves first-index semantics when duplicate
runs cross chunk boundaries. Set ``route_targets=False`` to broadcast queries,
including when supplying an unsorted sequence and a suitable custom search.

Reusable pools retain workers, not preloaded input: each submitted task still
serializes its chunk and assigned targets. Do not mutate input during pool use.
Custom searches must be importable, pickleable functions returning the first
matching local index, or ``None``.
"""

from __future__ import annotations

import gc
import os
import sys
from bisect import bisect_left
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from types import TracebackType
from typing import Any

from .algorithms import binary_search

SearchFunction = Callable[[Sequence[Any], Any], int | None]
IndexedTargets = list[tuple[int, Any]]
ChunkJob = tuple[int, int, IndexedTargets]
_STARTUP_TIMEOUT_SECONDS = 30.0


def effective_worker_count(size: int, workers: int | None = None) -> int:
    """Validate workers and cap them to input size and Windows' limit of 61."""
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


def _initialize_worker(startup_barrier: Any) -> None:
    # A shared multiprocessing barrier is passed only through initializer args,
    # where spawn can transfer its synchronization primitives safely.
    if startup_barrier is not None:
        startup_barrier.wait(timeout=_STARTUP_TIMEOUT_SECONDS)


def _worker_ready() -> int:
    return os.getpid()


def _search_chunk(
    values: Sequence[Any],
    targets: IndexedTargets,
    offset: int,
    search_func: SearchFunction,
    disable_gc: bool,
) -> list[tuple[int, int | None]]:
    previous_gc = gc.isenabled()
    if disable_gc:
        gc.disable()
    else:
        gc.enable()
    try:
        results = []
        for position, target in targets:
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
            results.append((position, index))
        return results
    finally:
        if previous_gc:
            gc.enable()
        else:
            gc.disable()


class ParallelSearchPool:
    """Reuse fully initialized workers across batches over one fixed sequence.

    Entering the context eagerly starts all ``worker_count`` workers. An empty
    sequence needs no workers. The startup readiness wait and initializer
    barrier each use a 30-second timeout; joining workers during cleanup can
    extend the total elapsed time. Running tasks are not forcibly terminated.
    Worker exceptions or abrupt exits propagate after pool cleanup. Startup and
    shutdown are separate from ``search_many`` so benchmarks can report them
    separately from steady-state batches. Each batch still transfers its data.

    Routing assumes sorted input; use ``route_targets=False`` for custom searches
    on unsorted input. ``disable_gc`` controls cyclic GC inside worker searches,
    restoring each worker's previous state even when a search raises.
    """

    def __init__(
        self,
        input_list: Sequence[Any],
        workers: int | None = None,
        search_func: SearchFunction = binary_search,
        *,
        route_targets: bool = True,
        disable_gc: bool = False,
    ) -> None:
        if type(route_targets) is not bool or type(disable_gc) is not bool:
            raise ValueError("route_targets and disable_gc must be Boolean")
        self._values = input_list
        self._ranges = chunk_ranges(len(input_list), workers)
        self._upper_bounds = [input_list[stop - 1] for _, stop in self._ranges]
        self._search_func = search_func
        self._route_targets = route_targets
        self._disable_gc = disable_gc
        self._executor: ProcessPoolExecutor | None = None
        self._entered = False
        self._closed = False

    @property
    def worker_count(self) -> int:
        """Configured workers after input-size and platform caps."""
        return len(self._ranges)

    def _open(self, *, prewarm: bool) -> None:
        if self._entered or self._closed:
            raise RuntimeError("a search pool can only be entered once")
        self._entered = True
        if not self.worker_count:
            return
        context = get_context("spawn")
        barrier = (
            context.Barrier(self.worker_count, timeout=_STARTUP_TIMEOUT_SECONDS)
            if prewarm
            else None
        )
        self._executor = ProcessPoolExecutor(
            max_workers=self.worker_count,
            mp_context=context,
            initializer=_initialize_worker,
            initargs=(barrier,),
        )
        if prewarm:
            try:
                futures = [self._executor.submit(_worker_ready) for _ in self._ranges]
                for future in as_completed(futures, timeout=_STARTUP_TIMEOUT_SECONDS):
                    future.result()
            except BaseException:
                # Initializer waits are also bounded, so shutdown cannot leave
                # workers waiting forever at a barrier after startup failure.
                self.close()
                raise

    def __enter__(self) -> ParallelSearchPool:
        self._open(prewarm=True)
        return self

    def close(self) -> None:
        """Join workers; safe to call repeatedly."""
        if self._executor is not None:
            executor, self._executor = self._executor, None
            executor.shutdown(wait=True, cancel_futures=True)
        self._closed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _jobs(self, targets: list[Any]) -> list[ChunkJob]:
        if not self._ranges or not targets:
            return []
        if not self._route_targets:
            indexed = list(enumerate(targets))
            return [(start, stop, indexed) for start, stop in self._ranges]
        assignments: dict[int, IndexedTargets] = {}
        for position, target in enumerate(targets):
            chunk = bisect_left(self._upper_bounds, target)
            if chunk == self.worker_count:
                continue
            start, _ = self._ranges[chunk]
            if target < self._values[start]:
                continue
            assignments.setdefault(chunk, []).append((position, target))
        return [(*self._ranges[chunk], indexed) for chunk, indexed in assignments.items()]

    def _execute(self, targets: list[Any], jobs: list[ChunkJob]) -> list[int | None]:
        results: list[int | None] = [None] * len(targets)
        if not jobs:
            return results
        executor = self._executor
        if executor is None:
            raise RuntimeError("search pool has no active workers")
        try:
            futures = [
                executor.submit(
                    _search_chunk,
                    self._values[start:stop],
                    indexed,
                    start,
                    self._search_func,
                    self._disable_gc,
                )
                for start, stop, indexed in jobs
            ]
            for future in as_completed(futures):
                for position, index in future.result():
                    current = results[position]
                    if index is not None and (current is None or index < current):
                        results[position] = index
        except BaseException:
            self.close()
            raise
        return results

    def search_many(self, lookup_values: Iterable[Any]) -> list[int | None]:
        """Search one batch using this context's existing workers."""
        if not self._entered or self._closed:
            raise RuntimeError("search_many requires an active search-pool context")
        targets = list(lookup_values)
        return self._execute(targets, self._jobs(targets))


def parallel_search_many(
    input_list: Sequence[Any],
    lookup_values: Iterable[Any],
    workers: int | None = None,
    search_func: SearchFunction = binary_search,
    *,
    route_targets: bool = True,
    disable_gc: bool = False,
) -> list[int | None]:
    """Return first global indices, including cold pool startup and shutdown.

    Routing requires sorted input; disable it for suitable unsorted custom
    searches. Empty batches and targets outside all chunk ranges avoid starting
    any worker. Worker failures propagate; children are joined before returning.
    Spawn requires callers to use a ``__main__`` guard on every platform.
    """
    pool = ParallelSearchPool(
        input_list,
        workers,
        search_func,
        route_targets=route_targets,
        disable_gc=disable_gc,
    )
    targets = list(lookup_values)
    jobs = pool._jobs(targets)
    if not jobs:
        return [None] * len(targets)
    try:
        pool._open(prewarm=False)
        return pool._execute(targets, jobs)
    finally:
        pool.close()


def parallel_search(
    input_list: Sequence[Any],
    lookup_value: Any,
    workers: int | None = None,
    search_func: SearchFunction = binary_search,
    *,
    route_targets: bool = True,
    disable_gc: bool = False,
) -> int | None:
    """Return the first global index, or ``None`` when absent."""
    return parallel_search_many(
        input_list,
        [lookup_value],
        workers,
        search_func,
        route_targets=route_targets,
        disable_gc=disable_gc,
    )[0]


def multiproc_test(
    func: SearchFunction,
    lst_size: int,
    seq: Sequence[Any],
    tgt: Any,
    cpu_cnt: int,
    *,
    route_targets: bool = True,
    disable_gc: bool = False,
) -> int | None:
    """Legacy entry point returning a global index instead of printing."""
    effective_worker_count(lst_size, cpu_cnt)
    if lst_size != len(seq):
        raise ValueError("lst_size must equal the sequence length")
    return parallel_search(
        seq,
        tgt,
        workers=cpu_cnt,
        search_func=func,
        route_targets=route_targets,
        disable_gc=disable_gc,
    )
