"""Repeat the noisy landmark comparisons with three complete order rotations."""

import json
from pathlib import Path

from scripts.study_sources import source_fingerprints
from search_algos.benchmarks import BenchmarkConfig, run_benchmarks
from search_algos.metadata import collect_metadata


def main() -> None:
    names = (
        "bisect",
        "neighbor_prepared",
        "radix",
        "adaptive_index",
        "dict_reverse",
        "guarded_prepared",
        "landmark_index",
    )
    root = Path(__file__).resolve().parents[1]
    study = {
        "study_schema_version": 1,
        "metadata": collect_metadata(),
        "source_sha256": source_fingerprints(root, "scripts/confirm_landmark.py"),
        "reports": [],
    }
    for cycle in range(3):
        offset = cycle * 3 % len(names)
        order = names[offset:] + names[:offset]
        for seed in (0, 42):
            print(f"Confirmation cycle {cycle + 1}, seed {seed}", flush=True)
            report = run_benchmarks(
                BenchmarkConfig(
                    sizes=(100000,),
                    datasets=("uniform", "gapped", "duplicates"),
                    queries=20000,
                    algorithms=order,
                    seed=seed,
                    repetitions=21,
                    warmups=3,
                    time_budget=0,
                )
            )
            study["reports"].append(report)
    output = root / "benchmarks" / "landmark_sprint" / "confirmation.json"
    output.write_text(json.dumps(study, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
