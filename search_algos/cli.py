"""Command-line parsing and text/JSON/CSV benchmark reporting."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

from .benchmarks import (
    ALGORITHM_NAMES,
    DATASET_NAMES,
    DEFAULT_ALGORITHMS,
    DEFAULT_DATASETS,
    BenchmarkConfig,
    run_benchmarks,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark verified search algorithms on reproducible workloads.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog="Compare saved runs with: search-algos compare BASELINE.json CANDIDATE.json --help",
    )
    parser.add_argument(
        "--size",
        "--sizes",
        dest="sizes",
        type=int,
        nargs="+",
        default=[1000],
        help="input sizes (zero is supported)",
    )
    parser.add_argument(
        "--datasets",
        choices=DATASET_NAMES,
        nargs="+",
        default=list(DEFAULT_DATASETS),
        help="sorted input distributions; adversarial is opt-in",
    )
    parser.add_argument(
        "--algorithms",
        choices=(*ALGORITHM_NAMES, "all"),
        nargs="+",
        default=list(DEFAULT_ALGORITHMS),
        help="algorithms to measure; defaults include radix and prepared alternatives, including landmark_index; certified_radix is opt-in; all also includes certified_radix and multiprocessing",
    )
    parser.add_argument("--seed", type=int, default=0, help="workload seed")
    parser.add_argument("--repetitions", type=int, default=7, help="measured batches per algorithm")
    parser.add_argument(
        "--warmups", type=int, default=1, help="unreported batches before measurement"
    )
    parser.add_argument("--queries", type=int, default=100, help="queries in each batch")
    parser.add_argument(
        "--hit-rate",
        type=float,
        default=0.5,
        help="requested fraction of successful queries, from 0 to 1",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="parallel workers; default available logical CPUs, capped to input size and platform limit",
    )
    parser.add_argument(
        "--gc",
        dest="gc_mode",
        choices=("enabled", "disabled"),
        default="disabled",
        help="cyclic GC policy during measurement, including workers",
    )
    parser.add_argument(
        "--max-linear-work",
        type=int,
        default=50_000_000,
        help="skip linear if size * queries * (repetitions + warmups) exceeds this limit; 0 disables",
    )
    parser.add_argument(
        "--time-budget",
        type=float,
        default=5.0,
        help="soft seconds budget per algorithm/workload, checked between batches; 0 disables",
    )
    parser.add_argument(
        "--format", choices=("text", "json", "csv"), default="text", help="output format"
    )
    parser.add_argument("--output", type=Path, help="write a report to this file instead of stdout")
    return parser


def render_report(report: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, indent=2, allow_nan=False) + "\n"
    if output_format == "csv":
        stream = io.StringIO(newline="")
        rows = []
        for record in report["results"]:
            row = {"schema_version": report["schema_version"], **report["metadata"], **record}
            rows.append(
                {
                    key: json.dumps(value) if isinstance(value, list) else value
                    for key, value in row.items()
                }
            )
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
        "Set, dictionary, and radix-directory construction and other index preparation appear under setup; total includes per-batch setup and lookup.",
        f"Cyclic GC during measurement: {config.get('gc_mode', 'unspecified')}.",
        "Rankings compare completed rows within the same workload, result kind, and timing scope.",
    ]
    result_descriptions = {
        "first_index": "first matching index or None",
        "membership": "whether the target is present (True/False)",
    }
    scope_descriptions = {
        "lookup_batch": "sequential lookup; total also includes per-batch setup",
        "batch_with_process_startup": "cold pool; includes process startup and shutdown",
        "batch_reused_pool": "reused pool; excludes separately reported startup and shutdown",
    }
    # Matching inputs alone do not make different result contracts or timing scopes comparable.
    groups: dict[tuple[int, str, str, str, str], list[dict[str, Any]]] = {}
    for row in report["results"]:
        key = (
            row["size"],
            row["dataset"],
            row["workload_id"],
            row["result_kind"],
            row["timing_scope"],
        )
        groups.setdefault(key, []).append(row)
    for (size, dataset, workload_id, result_kind, timing_scope), rows in groups.items():
        rows = sorted(
            rows,
            key=lambda row: (
                row.get("status", "complete") != "complete",
                row["total_median_ns"] if row["total_median_ns"] is not None else float("inf"),
            ),
        )
        fastest = next(
            (row["total_median_ns"] for row in rows if row.get("status", "complete") == "complete"),
            None,
        )
        lines.extend(
            [
                "",
                f"{dataset}, size {size}: {rows[0]['hits']} hits / {rows[0]['queries']} queries",
                f"Workload: {workload_id}",
                f"Result: {result_kind} ({result_descriptions.get(result_kind, 'custom result contract')})",
                f"Timing scope: {timing_scope} ({scope_descriptions.get(timing_scope, 'custom timing scope')})",
                f"{'algorithm':<22} {'status':<10} {'setup med':>12} {'lookup med':>12} {'lookup IQR':>12} {'total med':>12} {'ns/query':>12} {'vs fastest':>11}",
            ]
        )
        for row in rows:
            total = row["total_median_ns"]
            status = row.get("status", "complete")
            relative = "n/a"
            if status == "complete" and total is not None and fastest is not None:
                relative = (
                    f"{total / fastest:.2f}x" if fastest else ("1.00x" if not total else "n/a")
                )
            lines.append(
                f"{row['algorithm']:<22} {status:<10} "
                f"{_number(row['setup_median_ns'], 1e6):>12} {_number(row['lookup_median_ns'], 1e6):>12} "
                f"{_number(row['lookup_iqr_ns'], 1e6):>12} {_number(total, 1e6):>12} "
                f"{_number(row['per_query_median_ns'], precision=1):>12} {relative:>11}"
            )
        for row in rows:
            if row.get("reason"):
                lines.append(
                    f"  {row['algorithm']}: {row['reason']} ({row.get('repetitions_completed', 0)} measured batches completed)"
                )
            if row["algorithm"] == "parallel_warm":
                lines.append(
                    f"  parallel_warm lifecycle (excluded from batch totals): startup {_number(row.get('pool_startup_ns'), 1e6)} ms, shutdown {_number(row.get('pool_shutdown_ns'), 1e6)} ms"
                )
    lines.extend(
        [
            "",
            "ns/query is amortized lookup time. Rows rank by total median within each table; vs fastest is total / fastest complete total in that table (1.00x is fastest). Incomplete/skipped rows are not ranked. JSON/CSV include raw samples and workload IDs.",
        ]
    )
    return "\n".join(lines) + "\n"


def _number(value: float | None, divisor: float = 1, precision: int = 6) -> str:
    return "-" if value is None else f"{value / divisor:.{precision}f}"


def _write_output(text: str, path: Path | None) -> None:
    if path is None:
        sys.stdout.write(text)
    else:
        with path.open("w", encoding="utf-8", newline="") as output:
            output.write(text)


def _compare_main(argv: list[str]) -> int:
    from .comparison import compare_reports, load_report, render_comparison

    parser = argparse.ArgumentParser(
        prog="search-algos compare",
        description="Compare matching completed rows. IQR overlap is descriptive, not a significance test.",
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--metric", choices=("total", "lookup"), default="total")
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        compared = compare_reports(
            load_report(args.baseline), load_report(args.candidate), metric=args.metric
        )
        _write_output(render_comparison(compared, args.format), args.output)
    except (OSError, ValueError) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "compare":
        return _compare_main(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    if "all" in args.algorithms and len(args.algorithms) != 1:
        parser.error("use --algorithms all by itself")
    try:
        config = BenchmarkConfig(
            sizes=tuple(args.sizes),
            datasets=tuple(args.datasets),
            algorithms=ALGORITHM_NAMES if args.algorithms == ["all"] else tuple(args.algorithms),
            seed=args.seed,
            repetitions=args.repetitions,
            warmups=args.warmups,
            queries=args.queries,
            hit_rate=args.hit_rate,
            workers=args.workers,
            gc_mode=args.gc_mode,
            max_linear_work=args.max_linear_work,
            time_budget=args.time_budget,
        )
    except ValueError as error:
        parser.error(str(error))
    try:
        report = render_report(run_benchmarks(config), args.format)
        _write_output(report, args.output)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        return 1
    return 0
