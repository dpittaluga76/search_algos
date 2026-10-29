"""Reproducible workloads and repeated, verified search benchmarks.

Dataset generation and result verification are outside the timed regions.
Each sample times a full batch of queries, including Python loop overhead.
Set construction is timed separately; parallel batches include pool startup,
data transfer, result aggregation, and pool shutdown.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import random
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import perf_counter_ns

from .algorithms import (
    binary_search,
    binary_search_by_recursion,
    binary_search_std_lib,
    interpolation_search,
    linear_search,
)
from .parallel import effective_worker_count, parallel_search_many

INDEX_ALGORITHMS = {
    "linear": linear_search,
    "binary": binary_search,
    "bisect": binary_search_std_lib,
    "recursive": binary_search_by_recursion,
    "interpolation": interpolation_search,
}
DEFAULT_ALGORITHMS = (*INDEX_ALGORITHMS, "set")
ALGORITHM_NAMES = (*DEFAULT_ALGORITHMS, "parallel")
DATASET_NAMES = ("uniform", "gapped", "duplicates", "skewed")


def _integer(name: str, value: int, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class BenchmarkConfig:
    """All workload and measurement options, independent of CLI parsing."""

    sizes: tuple[int, ...] = (1000,)
    datasets: tuple[str, ...] = DATASET_NAMES
    algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS
    seed: int = 0
    repetitions: int = 7
    warmups: int = 1
    queries: int = 100
    hit_rate: float = 0.5
    workers: int | None = None

    def __post_init__(self) -> None:
        if not self.sizes:
            raise ValueError("at least one size is required")
        for size in self.sizes:
            _integer("size", size, 0)
        for label, selected, allowed in (
            ("datasets", self.datasets, DATASET_NAMES),
            ("algorithms", self.algorithms, ALGORITHM_NAMES),
        ):
            if not selected or any(name not in allowed for name in selected):
                raise ValueError(f"{label} must be selected from {', '.join(allowed)}")
        for label, selected in (
            ("sizes", self.sizes), ("datasets", self.datasets),
            ("algorithms", self.algorithms),
        ):
            if len(set(selected)) != len(selected):
                raise ValueError(f"{label} must not contain duplicates")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        _integer("repetitions", self.repetitions, 1)
        _integer("warmups", self.warmups, 0)
        _integer("queries", self.queries, 1)
        if (
            type(self.hit_rate) not in (int, float)
            or not math.isfinite(self.hit_rate)
            or not 0 <= self.hit_rate <= 1
        ):
            raise ValueError("hit_rate must be a finite number between 0 and 1")
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
    """Make sorted even-valued data and shuffled, guaranteed hit/miss queries.

    Half of the misses (when possible) are inside the observed value range;
    the others alternate below and above it. Odd-valued misses cannot collide
    with the even-valued input. Empty inputs necessarily have zero hits.
    """
    BenchmarkConfig(
        sizes=(size,), datasets=(dataset,), algorithms=("binary",),
        queries=queries, hit_rate=hit_rate, seed=seed,
    )
    rng = random.Random(f"{seed}:{dataset}:{size}:data")
    if dataset == "uniform":
        values = tuple(2 * i for i in range(size))
    elif dataset == "gapped":
        values = tuple(sorted(2 * i for i in rng.sample(range(size * 10), size)))
    elif dataset == "duplicates":
        values = tuple(sorted(2 * rng.randrange(max(1, size // 20)) for _ in range(size)))
    else:
        values = tuple(sorted(2 * rng.randrange(max(1, size * 10)) ** 3 for _ in range(size)))

    rng = random.Random(f"{seed}:{dataset}:{size}:queries")
    hit_count = round(queries * hit_rate) if values else 0
    targets = [rng.choice(values) for _ in range(hit_count)]
    low, high = (values[0], values[-1]) if values else (0, 0)
    for i in range(queries - hit_count):
        if i % 2 == 0 and low < high:
            target = 2 * rng.randrange(low // 2, high // 2) + 1
        elif i % 4 < 2:
            target = low - 1
        else:
            target = high + 1
        targets.append(target)
    rng.shuffle(targets)

    first_indices = {}
    for index, value in enumerate(values):
        first_indices.setdefault(value, index)
    expected = tuple(first_indices.get(target) for target in targets)
    encoded = json.dumps([values, targets], separators=(",", ":")).encode("utf-8")
    return Workload(values, tuple(targets), expected, hashlib.sha256(encoded).hexdigest())


def verify_results(algorithm: str, results: list, workload: Workload) -> None:
    """Reject incorrect results before any measurement is included in a report."""
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


def _measure_batch(algorithm: str, workload: Workload, workers: int | None) -> tuple[int, int]:
    setup_ns = 0
    if algorithm == "set":
        start = perf_counter_ns()
        index = set(workload.values)
        setup_ns = perf_counter_ns() - start
        start = perf_counter_ns()
        results = [target in index for target in workload.targets]
        lookup_ns = perf_counter_ns() - start
    elif algorithm == "parallel":
        start = perf_counter_ns()
        results = parallel_search_many(workload.values, workload.targets, workers=workers)
        lookup_ns = perf_counter_ns() - start
    else:
        search = INDEX_ALGORITHMS[algorithm]
        start = perf_counter_ns()
        results = [search(workload.values, target) for target in workload.targets]
        lookup_ns = perf_counter_ns() - start
    verify_results(algorithm, results, workload)
    return setup_ns, lookup_ns


def _iqr(samples: list[int]) -> float:
    if len(samples) < 2:
        return 0.0
    lower, _, upper = statistics.quantiles(samples, n=4, method="inclusive")
    return upper - lower


def run_benchmarks(config: BenchmarkConfig) -> dict:
    """Return configuration, environment metadata, summaries, and raw samples."""
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count() or 1,
        "timer": "perf_counter_ns",
        "multiprocessing_start_method": "spawn",
    }
    records = []
    for size in config.sizes:
        for dataset in config.datasets:
            workload = make_workload(
                size, dataset, queries=config.queries,
                hit_rate=config.hit_rate, seed=config.seed,
            )
            # Rotate order between repetitions so no algorithm always runs first.
            samples = {name: {"setup": [], "lookup": []} for name in config.algorithms}
            for iteration in range(config.warmups + config.repetitions):
                shift = iteration % len(config.algorithms)
                order = config.algorithms[shift:] + config.algorithms[:shift]
                for algorithm in order:
                    setup_ns, lookup_ns = _measure_batch(algorithm, workload, config.workers)
                    if iteration >= config.warmups:
                        samples[algorithm]["setup"].append(setup_ns)
                        samples[algorithm]["lookup"].append(lookup_ns)
            for algorithm in config.algorithms:
                setup = samples[algorithm]["setup"]
                lookup = samples[algorithm]["lookup"]
                total = [a + b for a, b in zip(setup, lookup)]
                hits = sum(index is not None for index in workload.expected_indices)
                records.append({
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
                    "requested_workers": config.workers,
                    "effective_workers": effective_worker_count(size, config.workers) if algorithm == "parallel" else 0,
                    "workload_id": workload.workload_id,
                    "timing_scope": "batch_with_process_startup" if algorithm == "parallel" else "lookup_batch",
                    "setup_median_ns": statistics.median(setup),
                    "setup_iqr_ns": _iqr(setup),
                    "lookup_median_ns": statistics.median(lookup),
                    "lookup_iqr_ns": _iqr(lookup),
                    "lookup_min_ns": min(lookup),
                    "lookup_max_ns": max(lookup),
                    "total_median_ns": statistics.median(total),
                    "total_iqr_ns": _iqr(total),
                    "per_query_median_ns": statistics.median(lookup) / config.queries,
                    "setup_samples_ns": setup,
                    "lookup_samples_ns": lookup,
                })
    return {"schema_version": 1, "metadata": metadata, "config": asdict(config), "results": records}
