"""Reproduce the ten-minute landmark-index experiment from the checkout."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.benchmark_certified import CUSTOM_DATASETS, make_custom_workload, measure_custom
from scripts.study_sources import source_fingerprints
from search_algos.benchmarks import DEFAULT_ALGORITHMS, BenchmarkConfig, run_benchmarks
from search_algos.cli import render_report
from search_algos.metadata import collect_metadata

FOCUSED = (
    "bisect",
    "radix",
    "dict",
    "dict_reverse",
    "neighbor_prepared",
    "guarded_prepared",
    "adaptive_index",
    "certified_radix",
    "landmark_index",
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "benchmarks" / "landmark_sprint"
    output.mkdir(parents=True, exist_ok=True)
    study: dict = {
        "study_schema_version": 1,
        "metadata": collect_metadata(),
        "source_sha256": source_fingerprints(
            root, "scripts/benchmark_landmark.py", "scripts/benchmark_certified.py"
        ),
        "reports": [],
        "custom_results": [],
    }
    for seed in (0, 1, 2, 42):
        print(f"Main workload, seed {seed}", flush=True)
        algorithms = DEFAULT_ALGORITHMS if seed == 0 else FOCUSED
        report = run_benchmarks(
            BenchmarkConfig(
                sizes=(100000,),
                datasets=("uniform", "gapped", "duplicates"),
                algorithms=algorithms,
                queries=20000,
                seed=seed,
            )
        )
        study["reports"].append(report)
        if seed == 0:
            (output / "default-cli.json").write_text(json.dumps(report, indent=2) + "\n")
            (output / "default-cli.txt").write_text(render_report(report, "text"), encoding="utf-8")
    config = BenchmarkConfig(sizes=(100000,), algorithms=FOCUSED, queries=20000, time_budget=0)
    for dataset in CUSTOM_DATASETS:
        print(f"Independent stress workload: {dataset}", flush=True)
        workload = make_custom_workload(100000, dataset, 20000, 0)
        study["custom_results"].extend(measure_custom(workload, dataset, config))
    (output / "results.json").write_text(json.dumps(study, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
