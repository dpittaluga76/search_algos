"""Reproducible, bounded benchmarks with explicit timing and GC policies.

Workload creation and correctness checks are outside the timers. Set/dictionary
construction is measured separately. Cold parallel batches include the whole
pool lifecycle; warm batches reuse workers and report their lifecycle separately.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from time import perf_counter, perf_counter_ns
from typing import Any

from .algorithms import (
    binary_search,
    binary_search_by_recursion,
    binary_search_std_lib,
    build_first_index,
    exponential_search,
    interpolation_search,
    interpolation_search_hybrid,
    jump_search,
    linear_search,
)
from .measurement import gc_policy
from .metadata import collect_metadata
from .parallel import ParallelSearchPool, effective_worker_count, parallel_search_many
from .validation import (
    validate_integer,
    validate_number,
    validate_query_options,
    validate_selection,
)

INDEX_ALGORITHMS: dict[str, Callable[[Sequence[int], int], int | None]] = {
    "linear": linear_search,
    "binary": binary_search,
    "bisect": binary_search_std_lib,
    "recursive": binary_search_by_recursion,
    "interpolation": interpolation_search,
    "interpolation_hybrid": interpolation_search_hybrid,
    "exponential": exponential_search,
    "jump": jump_search,
}
DEFAULT_ALGORITHMS = (*INDEX_ALGORITHMS, "set", "dict")
ALGORITHM_NAMES = (*DEFAULT_ALGORITHMS, "parallel", "parallel_warm")
DEFAULT_DATASETS = ("uniform", "gapped", "duplicates", "skewed")
DATASET_NAMES = (*DEFAULT_DATASETS, "adversarial")


@dataclass(frozen=True)
class BenchmarkConfig:
    """Options shared by the CLI and library; zero disables each run limit."""

    sizes: tuple[int, ...] = (1000,)
    datasets: tuple[str, ...] = DEFAULT_DATASETS
    algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS
    seed: int = 0
    repetitions: int = 7
    warmups: int = 1
    queries: int = 100
    hit_rate: float = 0.5
    workers: int | None = None
    gc_mode: str = "disabled"
    max_linear_work: int = 50_000_000
    time_budget: float = 5.0

    def __post_init__(self) -> None:
        if not self.sizes:
            raise ValueError("at least one size is required")
        for size in self.sizes:
            validate_integer("size", size)
        if len(set(self.sizes)) != len(self.sizes):
            raise ValueError("sizes must not contain duplicates")
        validate_selection("datasets", self.datasets, DATASET_NAMES)
        validate_selection("algorithms", self.algorithms, ALGORITHM_NAMES)
        validate_query_options(self.queries, self.hit_rate, self.seed)
        validate_integer("repetitions", self.repetitions, 1)
        validate_integer("warmups", self.warmups)
        validate_integer("max_linear_work", self.max_linear_work)
        validate_number("time_budget", self.time_budget)
        if self.gc_mode not in ("enabled", "disabled"):
            raise ValueError("gc_mode must be enabled or disabled")
        effective_worker_count(0, self.workers)


@dataclass(frozen=True)
class Workload:
    values: tuple[int, ...]
    targets: tuple[int, ...]
    expected_indices: tuple[int | None, ...]
    workload_id: str


def make_workload(
    size: int,
    dataset: str,
    *,
    queries: int = 100,
    hit_rate: float = 0.5,
    seed: int = 0,
) -> Workload:
    """Make sorted even-valued data with guaranteed hit/miss queries.

    The adversarial distribution has a dense prefix and a distant final value.
    Its first successful query (if any) targets the end of the dense prefix,
    exposing interpolation's linear worst case without huge exponential integers.
    """
    validate_integer("size", size)
    validate_selection("dataset", (dataset,), DATASET_NAMES)
    validate_query_options(queries, hit_rate, seed)
    rng = random.Random(f"{seed}:{dataset}:{size}:data")
    if dataset == "uniform":
        values = tuple(2 * i for i in range(size))
    elif dataset == "gapped":
        values = tuple(sorted(2 * i for i in rng.sample(range(size * 10), size)))
    elif dataset == "duplicates":
        values = tuple(sorted(2 * rng.randrange(max(1, size // 20)) for _ in range(size)))
    elif dataset == "skewed":
        values = tuple(sorted(2 * rng.randrange(max(1, size * 10)) ** 3 for _ in range(size)))
    elif size < 2:
        values = tuple(range(size))
    else:
        values = (*range(0, 2 * (size - 1), 2), 2 * max(10**12, size**3))

    rng = random.Random(f"{seed}:{dataset}:{size}:queries")
    hit_count = round(queries * hit_rate) if values else 0
    targets = [rng.choice(values) for _ in range(hit_count)]
    if dataset == "adversarial" and hit_count and size >= 2:
        targets[0] = values[-2]
    low, high = (values[0], values[-1]) if values else (0, 0)
    for i in range(queries - hit_count):
        if i % 2 == 0 and low < high:
            miss_high = values[-2] if dataset == "adversarial" and size > 2 else high
            target = 2 * rng.randrange(low // 2, miss_high // 2) + 1
        elif i % 4 < 2:
            target = low - 1
        else:
            target = high + 1
        targets.append(target)
    rng.shuffle(targets)

    first_indices = build_first_index(values)
    expected = tuple(first_indices.get(target) for target in targets)
    encoded = json.dumps([values, targets], separators=(",", ":")).encode("utf-8")
    return Workload(values, tuple(targets), expected, hashlib.sha256(encoded).hexdigest())


def verify_results(
    algorithm: str, results: Sequence[int | bool | None], workload: Workload
) -> None:
    """Reject incorrect results outside the measured regions."""
    if len(results) != len(workload.targets):
        raise RuntimeError(f"{algorithm} returned the wrong number of results")
    for target, result, expected in zip(workload.targets, results, workload.expected_indices):
        if algorithm == "set":
            correct = type(result) is bool and result == (expected is not None)
        else:
            correct = (result is None and expected is None) or (
                type(result) is int and result == expected
            )
        if not correct:
            expected_result = expected is not None if algorithm == "set" else expected
            raise RuntimeError(
                f"{algorithm} returned {result!r} for {target!r}; expected {expected_result!r}"
            )


def _measure_batch(
    algorithm: str,
    workload: Workload,
    config: BenchmarkConfig,
    pool: ParallelSearchPool | None = None,
) -> tuple[int, int]:
    setup_ns = 0
    results: Sequence[int | bool | None]
    with gc_policy(disabled=config.gc_mode == "disabled"):
        if algorithm == "set":
            start = perf_counter_ns()
            membership = set(workload.values)
            setup_ns = perf_counter_ns() - start
            start = perf_counter_ns()
            results = [target in membership for target in workload.targets]
        elif algorithm == "dict":
            start = perf_counter_ns()
            first_indices = build_first_index(workload.values)
            setup_ns = perf_counter_ns() - start
            start = perf_counter_ns()
            results = [first_indices.get(target) for target in workload.targets]
        elif algorithm == "parallel":
            start = perf_counter_ns()
            results = parallel_search_many(
                workload.values,
                workload.targets,
                workers=config.workers,
                disable_gc=config.gc_mode == "disabled",
            )
        elif algorithm == "parallel_warm":
            if pool is None:
                raise RuntimeError("parallel_warm requires an initialized pool")
            start = perf_counter_ns()
            results = pool.search_many(workload.targets)
        else:
            search = INDEX_ALGORITHMS[algorithm]
            start = perf_counter_ns()
            results = [search(workload.values, target) for target in workload.targets]
        lookup_ns = perf_counter_ns() - start
    verify_results(algorithm, results, workload)
    return setup_ns, lookup_ns


@dataclass
class _Measurements:
    setup: list[int] = field(default_factory=list)
    lookup: list[int] = field(default_factory=list)
    warmups_completed: int = 0
    elapsed_seconds: float = 0.0
    status: str = "complete"
    reason: str | None = None
    pool_startup_ns: int = 0
    pool_shutdown_ns: int = 0


def _summaries(samples: list[int], prefix: str) -> dict[str, float | None]:
    names = ("median", "q1", "q3", "iqr", "min", "max")
    if not samples:
        return {f"{prefix}_{name}_ns": None for name in names}
    if len(samples) == 1:
        q1 = q3 = float(samples[0])
    else:
        q1, _, q3 = statistics.quantiles(samples, n=4, method="inclusive")
    values = (statistics.median(samples), q1, q3, q3 - q1, min(samples), max(samples))
    return {f"{prefix}_{name}_ns": float(value) for name, value in zip(names, values)}


def _workload_measurements(workload: Workload, config: BenchmarkConfig) -> dict[str, _Measurements]:
    measurements = {name: _Measurements() for name in config.algorithms}
    linear_work = len(workload.values) * config.queries * (config.repetitions + config.warmups)
    if "linear" in measurements and config.max_linear_work and linear_work > config.max_linear_work:
        measurements["linear"].status = "skipped"
        measurements["linear"].reason = (
            f"estimated work {linear_work} exceeds max_linear_work {config.max_linear_work}; "
            "use --max-linear-work 0 to disable this limit"
        )
    pool: ParallelSearchPool | None = None
    try:
        for iteration in range(config.warmups + config.repetitions):
            shift = iteration % len(config.algorithms)
            order = config.algorithms[shift:] + config.algorithms[:shift]
            for algorithm in order:
                measured = measurements[algorithm]
                if measured.status != "complete":
                    continue
                if config.time_budget and measured.elapsed_seconds >= config.time_budget:
                    measured.status = "incomplete" if measured.lookup else "skipped"
                    measured.reason = (
                        f"soft time budget of {config.time_budget:g}s reached between batches; "
                        "use --time-budget 0 to disable this limit"
                    )
                    continue
                before = perf_counter()
                if algorithm == "parallel_warm" and pool is None:
                    with gc_policy(disabled=config.gc_mode == "disabled"):
                        start = perf_counter_ns()
                        pool = ParallelSearchPool(
                            workload.values,
                            workers=config.workers,
                            disable_gc=config.gc_mode == "disabled",
                        )
                        pool.__enter__()
                        measured.pool_startup_ns = perf_counter_ns() - start
                    measured.elapsed_seconds += perf_counter() - before
                    # A slow startup may consume the budget before the first batch.
                    if config.time_budget and measured.elapsed_seconds >= config.time_budget:
                        measured.status = "skipped"
                        measured.reason = "soft time budget exhausted during pool startup"
                        continue
                    before = perf_counter()
                setup_ns, lookup_ns = _measure_batch(algorithm, workload, config, pool)
                measured.elapsed_seconds += perf_counter() - before
                if iteration < config.warmups:
                    measured.warmups_completed += 1
                else:
                    measured.setup.append(setup_ns)
                    measured.lookup.append(lookup_ns)
    finally:
        if pool is not None:
            with gc_policy(disabled=config.gc_mode == "disabled"):
                start = perf_counter_ns()
                pool.__exit__(None, None, None)
                measurements["parallel_warm"].pool_shutdown_ns = perf_counter_ns() - start
    return measurements


def run_benchmarks(config: BenchmarkConfig) -> dict[str, Any]:
    """Return schema 2 reports, retaining explicit rows for skipped work.

    The time budget is per algorithm/workload and checked between complete
    batches, so one batch can exceed it. Only fully completed rows are ranked.
    """
    metadata = collect_metadata()
    metadata["gc_mode"] = config.gc_mode
    records: list[dict[str, Any]] = []
    for size in config.sizes:
        for dataset in config.datasets:
            workload = make_workload(
                size,
                dataset,
                queries=config.queries,
                hit_rate=config.hit_rate,
                seed=config.seed,
            )
            measurements = _workload_measurements(workload, config)
            for algorithm in config.algorithms:
                measured = measurements[algorithm]
                total = [a + b for a, b in zip(measured.setup, measured.lookup)]
                hits = sum(index is not None for index in workload.expected_indices)
                scopes = {
                    "parallel": "batch_with_process_startup",
                    "parallel_warm": "batch_reused_pool",
                }
                records.append(
                    {
                        "algorithm": algorithm,
                        "result_kind": "membership" if algorithm == "set" else "first_index",
                        "dataset": dataset,
                        "size": size,
                        "seed": config.seed,
                        "queries": config.queries,
                        "hits": hits,
                        "misses": config.queries - hits,
                        "requested_hit_rate": config.hit_rate,
                        "actual_hit_rate": hits / config.queries,
                        "repetitions": config.repetitions,
                        "warmups": config.warmups,
                        "repetitions_completed": len(measured.lookup),
                        "warmups_completed": measured.warmups_completed,
                        "completed_queries": len(measured.lookup) * config.queries,
                        "status": measured.status,
                        "reason": measured.reason,
                        "requested_workers": config.workers,
                        "effective_workers": effective_worker_count(size, config.workers)
                        if algorithm in scopes
                        else 0,
                        "workload_id": workload.workload_id,
                        "gc_mode": config.gc_mode,
                        "timing_scope": scopes.get(algorithm, "lookup_batch"),
                        "max_linear_work": config.max_linear_work,
                        "time_budget": config.time_budget,
                        "pool_startup_ns": measured.pool_startup_ns,
                        "pool_shutdown_ns": measured.pool_shutdown_ns,
                        **_summaries(measured.setup, "setup"),
                        **_summaries(measured.lookup, "lookup"),
                        **_summaries(total, "total"),
                        "per_query_median_ns": statistics.median(measured.lookup) / config.queries
                        if measured.lookup
                        else None,
                        "setup_samples_ns": measured.setup,
                        "lookup_samples_ns": measured.lookup,
                    }
                )
    return {"schema_version": 2, "metadata": metadata, "config": asdict(config), "results": records}
