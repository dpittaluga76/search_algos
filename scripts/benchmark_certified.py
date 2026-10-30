"""Reproduce the certified radix experiment without changing CLI workloads.

Run from the checkout: python -m scripts.benchmark_certified --output results.json
The output is a study document, not a CLI comparison report. Its ``cli_reports``
entries are ordinary schema-2 reports; custom workload and allocation results
are separate. Allocation tracing runs after all timed experiments.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import random
import statistics
import tracemalloc
from collections.abc import Callable
from pathlib import Path

from scripts.study_sources import source_fingerprints
from search_algos import build_first_index, build_first_index_reversed, build_radix_index
from search_algos.benchmarks import (
    DEFAULT_ALGORITHMS,
    PREPARED_ALGORITHMS,
    BenchmarkConfig,
    Workload,
    _workload_measurements,
    run_benchmarks,
)
from search_algos.metadata import collect_metadata

FOCUSED = (
    "bisect",
    "dict",
    "radix",
    "neighbor_prepared",
    "dict_reverse",
    "guarded_prepared",
    "adaptive_index",
    "certified_radix",
)
CUSTOM_DATASETS = ("mixed_uniform", "mixed_duplicates", "mixed_regions", "same_parity_gaps")


def make_custom_workload(size: int, dataset: str, queries: int, seed: int) -> Workload:
    """Make 50% hits and 50% in-range misses without the CLI's parity shortcut."""
    rng = random.Random(f"certified:{seed}:{dataset}:{size}")
    if dataset == "mixed_uniform":
        values = tuple(sorted(rng.sample(range(-8 * size, 8 * size), size)))
    elif dataset == "mixed_duplicates":
        keys = rng.sample(range(-size, size), max(2, size // 20))
        values = tuple(sorted(rng.choice(keys) for _ in range(size)))
    elif dataset == "same_parity_gaps":
        values = tuple(sorted(2 * key for key in rng.sample(range(-5 * size, 5 * size), size)))
    elif dataset == "mixed_regions":
        data: list[int] = []
        for block in range((size + 63) // 64):
            base = block * 256 - 2 * size
            kind = block % 4
            if kind == 0:
                offsets = list(range(0, 192, 3))
            elif kind == 1:
                offsets = sorted(rng.sample(range(256), 64))
            elif kind == 2:
                offsets = [37] * 64
            else:
                offsets = sorted(rng.choice((2, 9, 27, 31, 63, 110, 172)) for _ in range(64))
            data.extend(base + offset for offset in offsets)
        values = tuple(data[:size])
    else:
        raise ValueError(f"unknown custom dataset: {dataset}")
    miss_step = 2 if dataset == "same_parity_gaps" else 1
    if not any(right - left > miss_step for left, right in zip(values, values[1:])):
        raise ValueError("generated workload has no in-range misses; choose another seed")
    first = build_first_index(values)
    targets = [rng.choice(values) for _ in range(round(queries * 0.5))]
    while len(targets) < queries:
        if dataset == "same_parity_gaps":
            target = 2 * rng.randrange(values[0] // 2, values[-1] // 2 + 1)
        else:
            target = rng.randrange(values[0], values[-1] + 1)
        if target not in first:
            targets.append(target)
    rng.shuffle(targets)
    expected = tuple(first.get(target) for target in targets)
    encoded = json.dumps([values, targets], separators=(",", ":")).encode()
    return Workload(values, tuple(targets), expected, hashlib.sha256(encoded).hexdigest())


def measure_custom(workload: Workload, dataset: str, config: BenchmarkConfig) -> list[dict]:
    """Use the same rotation, GC policy, correctness gate, and timers as the CLI."""
    rows = []
    for name, measured in _workload_measurements(workload, config).items():
        totals = [a + b for a, b in zip(measured.setup, measured.lookup)]
        rows.append(
            {
                "dataset": dataset,
                "size": len(workload.values),
                "queries": len(workload.targets),
                "seed": config.seed,
                "workload_id": workload.workload_id,
                "hits": sum(index is not None for index in workload.expected_indices),
                "algorithm": name,
                "status": measured.status,
                "reason": measured.reason,
                "gc_mode": config.gc_mode,
                "warmups_completed": measured.warmups_completed,
                "setup_samples_ns": measured.setup,
                "lookup_samples_ns": measured.lookup,
                "setup_median_ns": statistics.median(measured.setup),
                "lookup_median_ns": statistics.median(measured.lookup),
                "total_median_ns": statistics.median(totals),
            }
        )
    return rows


def measure_allocations(values: tuple[int, ...]) -> list[dict]:
    """Trace incremental retained/peak Python allocations, excluding input data."""
    builders: dict[str, Callable] = {
        "dict": build_first_index,
        "dict_reverse": build_first_index_reversed,
        "radix": build_radix_index,
        **PREPARED_ALGORITHMS,
    }
    rows = []
    for name, builder in builders.items():
        gc.collect()
        tracemalloc.start()
        try:
            prepared = builder(values)
            retained, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        rows.append({"algorithm": name, "retained_bytes": retained, "peak_bytes": peak})
        del prepared
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=100_000)
    parser.add_argument("--queries", type=int, default=20_000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    if args.size < 100:
        parser.error("--size must be at least 100 for the custom distributions")
    options = dict(repetitions=args.repetitions, warmups=args.warmups, queries=args.queries)
    # Validate options before generating any custom workloads.
    BenchmarkConfig(sizes=(args.size,), **options)
    study: dict = {
        "study_schema_version": 1,
        "metadata": collect_metadata(),
        "options": {**vars(args), "output": str(args.output)},
        "cli_reports": [],
        "custom_results": [],
        "allocations": [],
    }
    root = Path(__file__).resolve().parents[1]
    study["source_sha256"] = source_fingerprints(root, "scripts/benchmark_certified.py")
    for seed_index, seed in enumerate(args.seeds):
        print(f"CLI distributions, seed {seed}", flush=True)
        algorithms = (*DEFAULT_ALGORITHMS, "certified_radix") if seed_index == 0 else FOCUSED
        study["cli_reports"].append(
            run_benchmarks(
                BenchmarkConfig(
                    sizes=(args.size,),
                    datasets=("uniform", "gapped", "duplicates"),
                    algorithms=algorithms,
                    seed=seed,
                    **options,
                )
            )
        )
        study["cli_reports"].append(
            run_benchmarks(
                BenchmarkConfig(
                    sizes=(args.size,),
                    datasets=("skewed", "adversarial"),
                    algorithms=FOCUSED,
                    seed=seed,
                    **options,
                )
            )
        )
        for dataset in CUSTOM_DATASETS:
            print(f"Custom {dataset}, seed {seed}", flush=True)
            workload = make_custom_workload(args.size, dataset, args.queries, seed)
            config = BenchmarkConfig(
                sizes=(args.size,), algorithms=FOCUSED, seed=seed, time_budget=0, **options
            )
            study["custom_results"].extend(measure_custom(workload, dataset, config))
    for queries in (max(1, args.size // 100), args.size * 2):
        print(f"Query-count sensitivity: {queries} queries", flush=True)
        study["cli_reports"].append(
            run_benchmarks(
                BenchmarkConfig(
                    sizes=(args.size,),
                    datasets=("uniform", "gapped", "duplicates"),
                    algorithms=FOCUSED,
                    seed=args.seeds[0],
                    repetitions=args.repetitions,
                    warmups=args.warmups,
                    queries=queries,
                    time_budget=0,
                )
            )
        )
    print("Allocation measurements (outside timing runs)", flush=True)
    for dataset in CUSTOM_DATASETS:
        workload = make_custom_workload(args.size, dataset, args.queries, args.seeds[0])
        for row in measure_allocations(workload.values):
            study["allocations"].append({"dataset": dataset, **row})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(study, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output}", flush=True)


if __name__ == "__main__":
    main()
