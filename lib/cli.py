"""Command-line parsing and text/JSON/CSV benchmark reporting."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

from .benchmarks import (
    ALGORITHM_NAMES,
    DATASET_NAMES,
    DEFAULT_ALGORITHMS,
    BenchmarkConfig,
    run_benchmarks,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark verified search algorithms on reproducible workloads.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--size", "--sizes", dest="sizes", type=int, nargs="+", default=[1000], help="input sizes (zero is supported)")
    parser.add_argument("--datasets", choices=DATASET_NAMES, nargs="+", default=list(DATASET_NAMES), help="sorted input distributions")
    parser.add_argument("--algorithms", choices=(*ALGORITHM_NAMES, "all"), nargs="+", default=list(DEFAULT_ALGORITHMS), help="algorithms to measure; all includes multiprocessing")
    parser.add_argument("--seed", type=int, default=0, help="workload seed")
    parser.add_argument("--repetitions", type=int, default=7, help="measured batches per algorithm")
    parser.add_argument("--warmups", type=int, default=1, help="unreported batches before measurement")
    parser.add_argument("--queries", type=int, default=100, help="queries in each batch")
    parser.add_argument("--hit-rate", type=float, default=0.5, help="requested fraction of successful queries, from 0 to 1")
    parser.add_argument("--workers", type=int, default=None, help="parallel workers; default available logical CPUs, capped to input size and platform limit")
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text", help="output format")
    parser.add_argument("--output", type=Path, help="write a report to this file instead of stdout")
    return parser


def render_report(report: dict, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, indent=2, allow_nan=False) + "\n"
    if output_format == "csv":
        stream = io.StringIO(newline="")
        rows = []
        for record in report["results"]:
            row = {"schema_version": report["schema_version"], **report["metadata"], **record}
            rows.append({key: json.dumps(value) if isinstance(value, list) else value for key, value in row.items()})
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return stream.getvalue()
    if output_format != "text":
        raise ValueError(f"unknown report format: {output_format}")

    config = report["config"]
    metadata = report["metadata"]
    lines = [
        f"Python {metadata['python_version']} ({metadata['python_implementation']}) | {metadata['platform']}",
        f"Seed {config['seed']} | {config['repetitions']} measured batches | {config['queries']} queries/batch | {config['warmups']} warmups",
        "Batch times are milliseconds; IQR is the interquartile range of lookup times.",
        "Set construction appears under setup; parallel lookup includes process startup and shutdown.",
        "Rows are ordered fastest to slowest by total median time (setup + lookup).",
        "",
        f"{'algorithm':<14} {'dataset':<11} {'size':>8} {'hits':>6} {'setup med':>12} {'lookup med':>12} {'lookup IQR':>12} {'total med':>12} {'ns/query':>12}",
    ]
    for row in sorted(report["results"], key=lambda row: row["total_median_ns"]):
        lines.append(
            f"{row['algorithm']:<14} {row['dataset']:<11} {row['size']:>8} {row['hits']:>6} "
            f"{row['setup_median_ns'] / 1e6:>12.6f} {row['lookup_median_ns'] / 1e6:>12.6f} "
            f"{row['lookup_iqr_ns'] / 1e6:>12.6f} {row['total_median_ns'] / 1e6:>12.6f} "
            f"{row['per_query_median_ns']:>12.1f}"
        )
    lines.extend(["", "ns/query is the amortized lookup batch time; total includes setup. JSON/CSV include raw samples and workload IDs."])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if "all" in args.algorithms and len(args.algorithms) != 1:
        parser.error("use --algorithms all by itself")
    try:
        config = BenchmarkConfig(
            sizes=tuple(args.sizes), datasets=tuple(args.datasets),
            algorithms=ALGORITHM_NAMES if args.algorithms == ["all"] else tuple(args.algorithms),
            seed=args.seed, repetitions=args.repetitions, warmups=args.warmups,
            queries=args.queries, hit_rate=args.hit_rate, workers=args.workers,
        )
    except ValueError as error:
        parser.error(str(error))
    try:
        report = render_report(run_benchmarks(config), args.format)
        if args.output is None:
            sys.stdout.write(report)
        else:
            with args.output.open("w", encoding="utf-8", newline="") as output:
                output.write(report)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 1
    return 0
