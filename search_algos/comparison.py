"""Compare saved benchmark samples without treating spread as significance."""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

Identity = tuple[str, str, str, str]
Scenario = tuple[str | None, int | None]
RowKey = tuple[Identity, Scenario]
IDENTITY_FIELDS = ("workload_id", "algorithm", "result_kind", "timing_scope")
_RATIO_DESCRIPTION = "baseline / candidate; values greater than 1 mean the candidate is faster"
_IQR_DESCRIPTION = "Overlap of observed [Q1, Q3] intervals; not a statistical significance test"


@dataclass(frozen=True)
class _Row:
    data: dict[str, Any]
    identity: Identity
    status: str
    setup: list[float]
    lookup: list[float]
    gc_mode: str | None

    @property
    def scenario(self) -> Scenario:
        return self.data.get("dataset"), self.data.get("size")

    def samples(self, metric: str) -> list[float]:
        if metric == "lookup":
            return self.lookup
        totals = [setup + lookup for setup, lookup in zip(self.setup, self.lookup)]
        if not all(math.isfinite(total) for total in totals):
            raise ValueError("paired setup and lookup samples must have finite totals")
        return totals


def _samples(value: Any, label: str) -> list[float]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of nonnegative finite numbers")
    result = []
    for sample in value:
        if type(sample) not in (int, float):
            raise ValueError(f"{label} must contain numbers, not booleans or other values")
        try:
            numeric = float(sample)
        except OverflowError as error:
            raise ValueError(f"{label} must contain finite numbers") from error
        if not math.isfinite(numeric) or numeric < 0:
            raise ValueError(f"{label} must contain nonnegative finite numbers")
        result.append(numeric)
    return result


def _count(
    data: dict[str, Any], field: str, label: str, *, minimum: int = 0, required: bool = False
) -> int | None:
    if field not in data and not required:
        return None
    value = data.get(field)
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} {field} must be an integer >= {minimum}")
    return value


def _validate_progress(
    data: dict[str, Any],
    config_counts: dict[str, int | None],
    sample_count: int,
    status: str,
    version: int,
    label: str,
) -> None:
    """Check completion evidence, allowing absent fields only in legacy rows."""
    requested = {}
    for field, minimum in (("queries", 1), ("repetitions", 1), ("warmups", 0)):
        value = _count(data, field, label, minimum=minimum, required=version == 2)
        configured = config_counts[field]
        if value is not None and configured is not None and value != configured:
            raise ValueError(f"{label} {field} conflicts with config: {value} versus {configured}")
        requested[field] = value if value is not None else configured
    completed = {
        field: _count(data, field, label, required=version == 2)
        for field in ("repetitions_completed", "warmups_completed", "completed_queries")
    }
    if completed["repetitions_completed"] not in (None, sample_count):
        raise ValueError(
            f"{label} repetitions_completed must equal timing sample count {sample_count}"
        )
    queries = requested["queries"]
    if queries is not None and completed["completed_queries"] not in (None, sample_count * queries):
        raise ValueError(
            f"{label} completed_queries must equal timing sample count * queries "
            f"({sample_count * queries})"
        )
    repetitions = requested["repetitions"]
    if repetitions is not None:
        if sample_count > repetitions:
            raise ValueError(
                f"{label} timing sample count exceeds requested repetitions {repetitions}"
            )
        if status == "complete" and sample_count != repetitions:
            raise ValueError(
                f"{label} is complete but timing sample count differs from repetitions"
            )
        if status == "incomplete" and sample_count == repetitions:
            raise ValueError(f"{label} is incomplete but all requested repetitions are present")
    if status == "incomplete" and sample_count == 0:
        raise ValueError(f"{label} is incomplete but has no timing samples; use skipped")
    warmups, warmups_completed = requested["warmups"], completed["warmups_completed"]
    if warmups is not None and warmups_completed is not None:
        if warmups_completed > warmups:
            raise ValueError(f"{label} warmups_completed exceeds requested warmups {warmups}")
        if sample_count and warmups_completed != warmups:
            raise ValueError(f"{label} contains timing samples before all warmups were completed")


def _validate_report(
    report: dict[str, Any], label: str
) -> tuple[dict[str, Any], dict[RowKey, _Row]]:
    if not isinstance(report, dict):
        raise ValueError(f"{label} must be a JSON object")
    version = report.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError(f"{label} has an unsupported benchmark schema_version; expected 1 or 2")
    metadata = report.get("metadata", {})
    config = report.get("config", {})
    if not isinstance(metadata, dict) or not isinstance(config, dict):
        raise ValueError(f"{label} metadata and config must be JSON objects")
    config_counts = {
        field: _count(config, field, f"{label} config", minimum=minimum)
        for field, minimum in (("queries", 1), ("repetitions", 1), ("warmups", 0))
    }
    results = report.get("results")
    if not isinstance(results, list):
        raise ValueError(f"{label} results must be a list")
    rows: dict[RowKey, _Row] = {}
    for position, data in enumerate(results):
        row_label = f"{label} results[{position}]"
        if not isinstance(data, dict):
            raise ValueError(f"{row_label} must be an object")
        for field in IDENTITY_FIELDS:
            if not isinstance(data.get(field), str) or not data[field]:
                raise ValueError(f"{row_label} needs a nonempty {field}")
        identity = cast(Identity, tuple(data[field] for field in IDENTITY_FIELDS))
        status = data.get("status", "complete" if version == 1 else None)
        if status not in ("complete", "incomplete", "skipped"):
            raise ValueError(f"{row_label} needs status complete, incomplete, or skipped")
        for field in ("size", "effective_workers"):
            if field in data and (type(data[field]) is not int or data[field] < 0):
                raise ValueError(f"{row_label} {field} must be a nonnegative integer")
        if "dataset" in data and not isinstance(data["dataset"], str):
            raise ValueError(f"{row_label} dataset must be a string")
        scenario: Scenario = data.get("dataset"), data.get("size")
        key = (identity, scenario)
        if key in rows:
            raise ValueError(f"{label} contains a duplicate row identity and scenario: {key}")
        setup = _samples(data.get("setup_samples_ns"), f"{row_label} setup_samples_ns")
        lookup = _samples(data.get("lookup_samples_ns"), f"{row_label} lookup_samples_ns")
        if len(setup) != len(lookup):
            raise ValueError(f"{row_label} setup and lookup sample counts differ")
        if status == "complete" and not lookup:
            raise ValueError(f"{row_label} is complete but has no timing samples")
        if status == "skipped" and lookup:
            raise ValueError(f"{row_label} is skipped but contains timing samples")
        _validate_progress(data, config_counts, len(lookup), status, version, row_label)
        gc_mode = data.get("gc_mode", config.get("gc_mode"))
        if gc_mode not in (None, "enabled", "disabled"):
            raise ValueError(f"{row_label} gc_mode must be enabled or disabled when specified")
        rows[key] = _Row(data, identity, status, setup, lookup, gc_mode)
    return metadata, rows


def _reject_constant(value: str) -> Any:
    raise ValueError(f"nonfinite JSON number {value} is not supported")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def load_report(path: Path) -> dict[str, Any]:
    """Read a report, requiring consistent completion evidence for schema 2.

    Legacy schema-1 progress fields remain optional, but any supplied counts
    must agree with raw samples and requested work.
    """
    try:
        report = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f"Cannot read benchmark report {path}: {error}") from error
    if not isinstance(report, dict):
        raise ValueError(f"Benchmark report {path} must be a JSON object")
    _validate_report(report, str(path))
    return cast(dict[str, Any], report)


def _summary(row: _Row | None, metric: str) -> tuple[float | None, float | None, float | None]:
    if row is None:
        return None, None, None
    samples = row.samples(metric)
    if not samples:
        return None, None, None
    samples = sorted(samples)
    lower_middle = samples[(len(samples) - 1) // 2]
    upper_middle = samples[len(samples) // 2]
    median = lower_middle + (upper_middle - lower_middle) / 2
    if len(samples) < 2:
        return median, None, None

    def quartile(numerator: int) -> float:
        index, remainder = divmod((len(samples) - 1) * numerator, 4)
        lower, upper = samples[index], samples[min(index + 1, len(samples) - 1)]
        return lower + (upper - lower) * (remainder / 4)

    return median, quartile(1), quartile(3)


def _match_rows(
    baseline: dict[RowKey, _Row], candidate: dict[RowKey, _Row]
) -> tuple[list[tuple[_Row | None, _Row | None]], bool]:
    """Use scenario labels only when the same actual workload occurs repeatedly."""
    baseline_groups: dict[Identity, dict[Scenario, _Row]] = {}
    candidate_groups: dict[Identity, dict[Scenario, _Row]] = {}
    for row in baseline.values():
        baseline_groups.setdefault(row.identity, {})[row.scenario] = row
    for row in candidate.values():
        candidate_groups.setdefault(row.identity, {})[row.scenario] = row
    identities = list(baseline_groups)
    identities.extend(identity for identity in candidate_groups if identity not in baseline_groups)
    pairs: list[tuple[_Row | None, _Row | None]] = []
    disambiguated = False
    for identity in identities:
        before = baseline_groups.get(identity, {})
        after = candidate_groups.get(identity, {})
        if len(before) <= 1 and len(after) <= 1:
            pairs.append((next(iter(before.values()), None), next(iter(after.values()), None)))
            continue
        disambiguated = True
        scenarios = list(before)
        scenarios.extend(scenario for scenario in after if scenario not in before)
        pairs.extend((before.get(scenario), after.get(scenario)) for scenario in scenarios)
    return pairs, disambiguated


def compare_reports(
    baseline: dict[str, Any], candidate: dict[str, Any], metric: str = "total"
) -> dict[str, Any]:
    """Match compatible rows and compare medians and observed sample intervals.

    Missing, skipped, and incomplete rows remain visible without speed ratios.
    Quartile overlap is reported only with at least two samples on both sides.
    Summary timing fields in inputs are not trusted: all statistics are
    recomputed from raw samples, pairing setup and lookup for total timings.
    A unique workload identity can match despite renamed dataset labels. If an
    identity repeats on either side, dataset and size disambiguate its rows;
    samples from separate scenarios are never combined.
    """
    if metric not in ("total", "lookup"):
        raise ValueError("metric must be total or lookup")
    baseline_meta, baseline_rows = _validate_report(baseline, "baseline")
    candidate_meta, candidate_rows = _validate_report(candidate, "candidate")
    warnings = []
    for field in ("cpu_model", "platform", "machine", "python_version", "python_implementation"):
        before, after = baseline_meta.get(field), candidate_meta.get(field)
        if before is None or before == "" or after is None or after == "":
            warnings.append(
                f"{field} is unavailable in one or both reports; environment compatibility is unknown"
            )
        elif before != after:
            warnings.append(f"{field} differs: baseline={before!r}, candidate={after!r}")
    for label, rows in (("baseline", baseline_rows), ("candidate", candidate_rows)):
        if any(row.gc_mode is None for row in rows.values()):
            warnings.append(
                f"{label} has rows without a GC policy; GC compatibility cannot be established for them"
            )

    pairs, disambiguated = _match_rows(baseline_rows, candidate_rows)
    if disambiguated:
        warnings.append(
            "Repeated workload identities are matched by dataset and size; unmatched scenarios remain visible"
        )
    comparisons = []
    for before, after in pairs:
        source = before if before is not None else after
        assert source is not None
        before_median, before_q1, before_q3 = _summary(before, metric)
        after_median, after_q1, after_q3 = _summary(after, metric)
        row: dict[str, Any] = {
            **dict(zip(IDENTITY_FIELDS, source.identity)),
            "size": source.data.get("size"),
            "dataset": source.data.get("dataset"),
            "baseline_status": before.status if before else None,
            "candidate_status": after.status if after else None,
            "baseline_median_ns": before_median,
            "candidate_median_ns": after_median,
            "baseline_q1_ns": before_q1,
            "baseline_q3_ns": before_q3,
            "candidate_q1_ns": after_q1,
            "candidate_q3_ns": after_q3,
            "speedup": None,
            "iqr_overlap": None,
            "status": "compared",
            "reason": None,
            "warnings": [],
        }
        conflicting_dimensions = []
        if before is not None and after is not None:
            for dimension in ("size", "queries"):
                previous, current = before.data.get(dimension), after.data.get(dimension)
                if previous is not None and current is not None and previous != current:
                    conflicting_dimensions.append(
                        f"{dimension} differs: {previous} versus {current}"
                    )
        if before is None or after is None:
            missing = "baseline" if before is None else "candidate"
            row["status"] = f"missing_{missing}"
            row["reason"] = f"No matching row in {missing}"
        elif before.status != "complete" or after.status != "complete":
            row["status"] = (
                "skipped" if "skipped" in (before.status, after.status) else "incomplete"
            )
            row["reason"] = (
                f"Baseline is {before.status}; candidate is {after.status}; only complete runs are compared"
            )
            reasons = [
                str(item.data["reason"]) for item in (before, after) if item.data.get("reason")
            ]
            if reasons:
                row["reason"] += ": " + "; ".join(reasons)
        elif conflicting_dimensions:
            row["status"] = "incomparable"
            row["reason"] = "Workload metadata conflicts despite matching IDs: " + "; ".join(
                conflicting_dimensions
            )
        elif (
            before.gc_mode is not None
            and after.gc_mode is not None
            and before.gc_mode != after.gc_mode
        ):
            row["status"] = "incomparable"
            row["reason"] = f"GC policies differ: {before.gc_mode} versus {after.gc_mode}"
        else:
            assert before_median is not None and after_median is not None
            if after_median:
                ratio = before_median / after_median
                if math.isfinite(ratio):
                    row["speedup"] = ratio
                else:
                    row["reason"] = "Speed ratio exceeds floating-point range"
            elif before_median == 0:
                row["speedup"] = 1.0
            else:
                row["reason"] = "Candidate median is zero; speed ratio is undefined"
            if None not in (before_q1, before_q3, after_q1, after_q3):
                assert before_q1 is not None and before_q3 is not None
                assert after_q1 is not None and after_q3 is not None
                row["iqr_overlap"] = max(before_q1, after_q1) <= min(before_q3, after_q3)
            before_workers = before.data.get("effective_workers")
            after_workers = after.data.get("effective_workers")
            if (
                before_workers is not None
                and after_workers is not None
                and before_workers != after_workers
            ):
                row["warnings"].append(
                    f"Worker counts differ: {before_workers} versus {after_workers}"
                )
        comparisons.append(row)
    return {
        "schema_version": 1,
        "metric": metric,
        "ratio_definition": _RATIO_DESCRIPTION,
        "iqr_interpretation": _IQR_DESCRIPTION,
        "baseline_metadata": baseline_meta,
        "candidate_metadata": candidate_meta,
        "warnings": warnings,
        "comparisons": comparisons,
    }


def render_comparison(report: dict[str, Any], format: str = "text") -> str:
    """Render comparison output as a readable table, JSON, or flat CSV."""
    if format == "json":
        return json.dumps(report, indent=2, allow_nan=False) + "\n"
    if format == "csv":
        stream = io.StringIO(newline="")
        fieldnames = [
            "metric",
            *IDENTITY_FIELDS,
            "size",
            "dataset",
            "baseline_status",
            "candidate_status",
            "baseline_median_ns",
            "candidate_median_ns",
            "baseline_q1_ns",
            "baseline_q3_ns",
            "candidate_q1_ns",
            "candidate_q3_ns",
            "speedup",
            "iqr_overlap",
            "status",
            "reason",
            "warnings",
            "report_warnings",
        ]
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in report["comparisons"]:
            writer.writerow(
                {
                    "metric": report["metric"],
                    **row,
                    "warnings": json.dumps(row["warnings"]),
                    "report_warnings": json.dumps(report["warnings"]),
                }
            )
        return stream.getvalue()
    if format != "text":
        raise ValueError("comparison format must be text, json, or csv")

    lines = [
        f"Comparison metric: {report['metric']} (median milliseconds)",
        f"Speedup: {report['ratio_definition']}.",
        f"IQR overlap: {report['iqr_interpretation']}.",
    ]
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    lines.extend(
        [
            "",
            f"{'algorithm':<22} {'workload':<20} {'baseline ms':>12} {'candidate ms':>12} {'speedup':>10} {'IQR overlap':>12} {'status':<18}",
        ]
    )
    for row in report["comparisons"]:
        before = (
            "n/a" if row["baseline_median_ns"] is None else f"{row['baseline_median_ns'] / 1e6:.6f}"
        )
        after = (
            "n/a"
            if row["candidate_median_ns"] is None
            else f"{row['candidate_median_ns'] / 1e6:.6f}"
        )
        speedup = "n/a" if row["speedup"] is None else f"{row['speedup']:.2f}x"
        overlap = "n/a" if row["iqr_overlap"] is None else ("yes" if row["iqr_overlap"] else "no")
        workload = f"{row['dataset'] or '?'}/{row['size'] if row['size'] is not None else '?'}"
        lines.append(
            f"{row['algorithm']:<22} {workload:<20} {before:>12} {after:>12} "
            f"{speedup:>10} {overlap:>12} {row['status']:<18}"
        )
        if row["reason"]:
            lines.append(f"  {row['reason']}")
        lines.extend(f"  Warning: {warning}" for warning in row["warnings"])
    if not report["comparisons"]:
        lines.append("No result rows.")
    return "\n".join(lines) + "\n"
