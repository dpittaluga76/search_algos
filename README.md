# Search algorithms benchmark

Compare Python search algorithms on reproducible workloads, with correctness
checks and separate measurements for lookup and preparation costs. The runtime
uses only the Python standard library. The project targets Python 3.10 through
3.14, with CI configured to test those versions on Windows and Linux.

## Quick start

Run from the repository without installing anything:

```console
python -m search_algos
python -m search_algos --size 100 1000 --datasets uniform gapped --seed 42
```

The existing script command remains supported through a compatibility launcher:

```console
python search_algos.py --size 1000 --seed 42
```

Or install the package and use its command:

```console
python -m pip install .
search-algos --size 1000 --algorithms binary bisect interpolation
```

The default run uses 1,000 elements, four dataset distributions, ten sequential
algorithms, 100 queries per batch, one warmup batch, seven measured batches, and
seed 0. Cyclic garbage collection is disabled during measurements. The
adversarial dataset and both multiprocessing modes are opt-in. Process startup
usually costs much more than a single binary search.

## Command-line options

| Option | Meaning | Default |
| --- | --- | --- |
| `--size`, `--sizes` | One or more nonnegative dataset sizes | `1000` |
| `--datasets` | One or more of `uniform`, `gapped`, `duplicates`, `skewed`, `adversarial` | All except `adversarial` |
| `--algorithms` | One or more names from the list below; use `all` alone for all twelve | Ten sequential algorithms |
| `--seed` | Integer random seed | `0` |
| `--repetitions` | Positive number of measured batches | `7` |
| `--warmups` | Nonnegative number of discarded warmup batches | `1` |
| `--queries` | Positive number of queries per batch | `100` |
| `--hit-rate` | Requested fraction of queries that find a value, from 0 to 1 | `0.5` |
| `--workers` | Positive worker count for multiprocessing | Available CPU count |
| `--gc` | Cyclic GC policy during measurements: `enabled` or `disabled` | `disabled` |
| `--max-linear-work` | Skip linear search when `size × queries × (repetitions + warmups)` exceeds this limit; `0` disables the limit | `50000000` |
| `--time-budget` | Soft execution budget in seconds per algorithm/workload; `0` disables the budget | `5` |
| `--format` | `text`, `json`, or `csv` | `text` |
| `--output` | Destination file; its parent directory must exist | Standard output |

Use `--help` for the full command reference. A zero-size dataset is valid and
has no successful queries, regardless of the requested hit rate. Other hit
counts are rounded to a whole number of queries. Worker counts are capped by
the number of elements, and by 61 on Windows. Algorithm names are `linear`,
`binary`, `bisect`, `recursive`, `interpolation`, `interpolation_hybrid`,
`exponential`, `jump`, `set`, `dict`, `parallel`, and `parallel_warm`.

The work limit prevents unexpectedly expensive linear scans before they start.
The time budget includes warmups and is checked between batches: it cannot
interrupt an already-running batch, so a batch can exceed the budget. Skipped
and incomplete rows remain in the report with a reason and completed sample
counts. They are excluded from rankings and speed comparisons. Use both
`--max-linear-work 0 --time-budget 0` when deliberately running unrestricted work.

Export a reproducible comparison:

```console
python -m search_algos --size 1000 10000 --datasets uniform duplicates skewed --seed 42 --format json --output results.json
python -m search_algos --size 1000 --datasets gapped --algorithms binary set --format csv --output results.csv
```

Include the full cost of multiprocessing:

```console
python -m search_algos --size 10000 --datasets gapped --algorithms binary parallel --workers 2 --queries 100 --repetitions 5
```

Compare cold and reused pools, or expose interpolation's worst case:

```console
python -m search_algos --size 10000 --datasets gapped --algorithms binary parallel parallel_warm --workers 2
python -m search_algos --size 100000 --datasets adversarial --algorithms binary interpolation interpolation_hybrid --queries 4 --repetitions 3
```

## Compare saved reports

```console
python -m search_algos --size 1000 --seed 42 --format json --output baseline.json
python -m search_algos --size 1000 --seed 42 --format json --output candidate.json
python -m search_algos compare baseline.json candidate.json
python -m search_algos compare baseline.json candidate.json --metric lookup --format csv --output comparison.csv
```

The same `compare` subcommand works with `search-algos` and the compatibility
script. It accepts benchmark report schemas 1 and 2. `--metric total` is the
default; `lookup` excludes per-batch index construction. Output can be text,
JSON, or CSV, with `--output` selecting a file instead of standard output.

Schema 2 reports must include per-row `queries`, `repetitions`, `warmups`,
`repetitions_completed`, `warmups_completed`, and `completed_queries` counts.
Requested query and repetition counts must be positive integers; warmup and
completed-work counts must be nonnegative integers. Boolean counts are rejected.
Requested counts must agree with the report configuration when it provides them.
The setup and lookup sample lists must have the same length, matching
`repetitions_completed`, and `completed_queries` must equal that length times
`queries`. Measured samples require all requested warmups to have completed.

A `complete` row must contain all requested measured batches and warmups. An
`incomplete` row must have some measured batches but fewer than requested; a
`skipped` row has no measured samples. Completed counts cannot exceed requested
counts. Inconsistent reports are rejected with an error identifying the affected
row, rather than producing a speed ratio. Schema 1 reports may omit these count
fields; any supplied counts are still checked for consistency.

Rows match by workload identifier, algorithm, result kind, and timing scope.
If identical workloads appear under multiple scenario labels, dataset and size
disambiguate those rows without merging their samples. Conflicting known size
or query counts make a matched pair incomparable.
The speed ratio is **baseline / candidate**: values above 1 mean the candidate
is faster. Missing, skipped, or incomplete rows are reported explicitly. Known
GC policies must agree; an unavailable policy in an older report produces a
warning. Hardware/runtime metadata differences are also surfaced for context.

Quartile overlap uses the actual `[Q1, Q3]` intervals derived from raw samples,
including paired setup-plus-lookup samples when comparing totals. It is a
description of the observed samples, **not a statistical significance test**.
Overlap is unavailable unless both rows contain at least two measured samples.
Cold and reused-pool timings have different scopes and are not interchangeable.

## Search API

Search functions are quiet and return their results directly:

```python
from search_algos import binary_search, binary_search_by_recursion, find_by_sets

values = [1, 3, 3, 8]
assert binary_search(values, 3) == 1
assert binary_search_by_recursion(values, 9) is None
assert find_by_sets(values, 8) is True
assert find_by_sets(values, 9) is False
```

| Function | Input requirements | Result |
| --- | --- | --- |
| `linear_search` | Sequence of comparable values; sorting is unnecessary | First matching index, or `None` |
| `binary_search` | Sequence sorted in ascending order | First matching index, or `None` |
| `binary_search_std_lib` | Sequence sorted in ascending order | First matching index, or `None` |
| `binary_search_by_recursion` | Sequence sorted in ascending order | First matching index, or `None` |
| `interpolation_search` | Ascending, finite numeric values | First matching index, or `None` |
| `interpolation_search_hybrid` | Ascending, finite numeric values | First match; falls back to binary search after a logarithmic probe limit |
| `exponential_search` | Sequence sorted in ascending order | First match using galloping bounds followed by binary search |
| `jump_search` | Sequence sorted in ascending order | First match using square-root blocks and a linear block scan |
| `find_by_sets` | Iterable of hashable values and a hashable target | `True` or `False` |
| `build_first_index` | Iterable of hashable values; sorting is unnecessary | Dictionary mapping each value to its first index |
| `find_by_dict` | Iterable of hashable values and a hashable target | First matching index, or `None`; builds an index for this call |

Sorted-input requirements are preconditions: the functions do not sort or scan
the input to validate ordering, since that would change the cost being measured.
Use the two-argument recursive search API to let it manage its bounds. Explicit
`left` and `right` bounds remain available; `right` is inclusive and both bounds
must describe a valid search range. Within a bounded search, the result is the
first matching index in that range. Boolean bounds are rejected.

`find_by_sets` and `find_by_dict` construct their hash structures on every call.
For repeated lookups, construct the structure once and reuse it:

```python
from search_algos import build_first_index

index = build_first_index([3, 1, 3, 2])
assert index.get(3) == 0
assert index.get(9) is None
```

The benchmark's `set` and `dict` rows measure construction separately from the
subsequent query batch. The dictionary baseline returns first indices, making
its result contract match the index-search algorithms.

Plain interpolation remains available to demonstrate distribution-sensitive
performance. The hybrid attempts at most `len(input_list).bit_length()`
interpolation probes before searching the remaining interval with binary search.

The optional `show_runtime_and_result` and `profile_this` decorators remain
available from `search_algos`. They return the wrapped function's result; search functions
are not decorated automatically. Timing a recursive search therefore surrounds
the complete call once. Result formatting distinguishes indices, missing values,
and Boolean membership results.

## Multiprocessing API

`parallel_search` and `parallel_search_many` partition a sorted sequence and
route each target to the earliest chunk whose value range could contain it.
This preserves the first matching global index when duplicates cross chunk
boundaries. Targets outside all ranges, including gaps between chunks, do not
require a worker search. Remainder elements are included, and empty work does
not start workers.

Use the main guard when starting processes, including on Unix: the implementation
uses the `spawn` start method on every platform.

```python
from search_algos import parallel_search, parallel_search_many

if __name__ == "__main__":
    values = [1, 2, 3, 4, 5]
    assert parallel_search(values, 5, workers=2) == 4
    assert parallel_search_many(values, [1, 5, 9], workers=2) == [0, 4, None]
```

Both functions accept `search_func`, defaulting to `binary_search`. Custom search
functions must be importable module-level functions that accept a sequence and
a target, then return the first matching local index or `None`. Worker exceptions
and abrupt worker exits propagate to the caller. Pools clean up their workers
when the operation finishes or fails.

Routing requires sorted input even for custom searches. Pass
`route_targets=False` to broadcast queries, including when using an unsorted
sequence with a suitable custom search such as `linear_search`.

Reuse initialized workers explicitly with `ParallelSearchPool`:

```python
from search_algos import ParallelSearchPool

if __name__ == "__main__":
    with ParallelSearchPool([1, 2, 2, 4], workers=2) as pool:
        assert pool.search_many([2, 9]) == [1, None]
        assert pool.search_many([4, 1]) == [3, 0]
```

Entering the context eagerly initializes the configured workers; leaving it
joins them. A reused pool retains workers, not preloaded input: each task still
transfers its chunk and assigned targets. Do not mutate the input during pool
use. `disable_gc=True` controls cyclic GC inside worker searches; the default
for direct API calls is `False`. Each worker restores its previous GC state.

The legacy `multiproc_test(func, lst_size, seq, tgt, cpu_cnt)` entry point remains
available and now returns a global index or `None`. It rejects a `lst_size` that
does not match the sequence. The unused `multiproc_gensample` helper and
algorithm-level queue parameters have been removed; use the multiprocessing API
instead.

## Workloads and interpretation

All algorithms in a comparison receive the same sequence and queries. Dataset
generation, sorting, expected-result calculation, and correctness verification
are outside the lookup timer.

Index searches locate the first occurrence of a value; set lookup answers only
whether the value is present. The exported `result_kind` field identifies these
operations as `first_index` and `membership`. Sharing workloads makes the inputs
comparable, but the operations provide different information; interpret their
timings according to the result your application needs.

- **Uniform:** evenly spaced unique values.
- **Gapped:** sampled values with irregular gaps.
- **Duplicates:** values sampled from a small domain.
- **Skewed:** uneven spacing across the numeric range.
- **Adversarial:** a dense prefix followed by a distant outlier. If there are
  successful queries, one targets the end of the dense prefix to expose plain
  interpolation's linear worst case. This distribution is opt-in.

Datasets use even integers and absent targets use odd integers, so misses are
known in advance. Present targets are selected from the generated sequence.
The seed controls generation and query selection. A SHA-256 workload identifier
records the actual sequence and targets; it can be compared across exports.
Identical workloads do not imply identical timings.

Each measured sample is a complete batch of queries. Reports include medians
and interquartile ranges (IQR), with per-query times derived from batch times.
The IQR describes the middle half of the observed samples; it is zero for a
single repetition. Every measured batch is checked against expected results
after timing, and an incorrect result aborts the run. Algorithm order rotates
between repetitions to reduce bias from always running the same algorithm first.

Set and first-index dictionary construction are timed separately on every
repetition. Total cost combines per-batch preparation and lookup, making the
query count relevant to how construction cost is amortized. Sequential lookups
include the Python loop that executes the queries.

`parallel` measures cold calls including routing, process startup, serialization,
result aggregation, and pool shutdown for each batch. It may start fewer workers
than the configured cap, or none when all targets can be rejected by routing.
`parallel_warm` reuses an eagerly initialized pool across warmups and measured
batches; it still includes routing, serialization, and result aggregation.
Its pool startup and shutdown are reported separately and excluded from batch
totals. The `effective_workers` field is the capped configuration, not a count
of processes observed performing work.

By default, cyclic GC is disabled during timing and explicitly disabled in
worker searches. `--gc enabled` measures with it enabled. The caller's prior GC
state is restored even after an exception. Disabling cyclic GC does not remove
reference-counting costs or other scheduling noise.

Text output separates each workload (identifier, size, and dataset) into tables
by result kind and timing scope. Each table identifies whether the result is a first
matching index or Boolean membership, and whether timing covers sequential
batches, cold process pools, or reused pools. Completed rows are ordered fastest
to slowest by total median time, including per-batch setup and lookup costs.
Its `vs fastest` column divides each total by the fastest completed total in
that compatible group. Membership results are not ranked against first-index
results, and cold and reused-pool timings have separate rankings. A group with
one completed row has no competing algorithm; its `1.00x` is only a reference
within that group. Incomplete and skipped rows are shown without rankings.
JSON includes configuration, runtime metadata, result summaries, and individual
timing samples. CSV repeats metadata alongside
each result and encodes sample lists as JSON within cells. The schema version is
`2`; result records include:

| Field | Interpretation |
| --- | --- |
| `status`, `reason` | `complete`, `incomplete`, or `skipped`, plus an explanation when work was limited |
| `repetitions_completed`, `warmups_completed` | Number of completed measured and warmup batches |
| `setup_median_ns` | Median set/dictionary construction cost; zero for other algorithms |
| `lookup_median_ns` | Median time for a complete batch of queries |
| `total_median_ns` | Median of each repetition's setup plus lookup time |
| `setup_iqr_ns`, `lookup_iqr_ns`, `total_iqr_ns` | Variability in each measured phase |
| `setup_q1_ns`, `setup_q3_ns`, and corresponding lookup/total fields | Actual quartile endpoints |
| `per_query_median_ns` | Median lookup batch time divided by query count |
| `setup_samples_ns`, `lookup_samples_ns` | Individual samples in nanoseconds |
| `timing_scope` | `lookup_batch`, `batch_with_process_startup`, or `batch_reused_pool` |
| `pool_startup_ns`, `pool_shutdown_ns` | Separate lifecycle measurements for `parallel_warm`; excluded from its batch totals |
| `gc_mode` | Recorded cyclic-GC measurement policy |
| `workload_id` | SHA-256 identifier of the sequence and queries |

Rows without measured samples have null summaries. Incomplete rows retain their
samples for diagnosis but are not treated as completed comparisons.

Runtime metadata includes the Python implementation/version, platform, CPU model,
package version, Git commit, and dirty-checkout status. Unavailable fields are
null. Git provenance comes from the executing source checkout; an installed
package does not borrow the Git revision of the caller's working directory.
Warmups and repeated measurements reduce some noise, but CPU load, scheduling,
caching, and machine differences
still affect results. Each repetition reuses the same workload.

## Development and verification

The unittest suite can run without third-party dependencies:

```console
python -m unittest discover -s tests -v
```

Install the pinned development tools for linting, formatting, strict package
type checks, and branch coverage:

```console
python -m pip install ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m mypy --package search_algos
python -m coverage erase
python -m coverage run -m unittest discover -s tests -v
python -m coverage combine
python -m coverage report
python -m coverage xml
python scripts/verify_release.py
```

Coverage includes CLI subprocesses and spawned workers, combines their results,
and writes `coverage.xml`. The coverage report enforces a 95% minimum combined
statement and branch coverage score. Coverage-instrumented test timings are not
performance measurements. The wheel ships a `py.typed` marker for downstream
type checkers.

`python scripts/verify_release.py` builds a wheel and installs it into a fresh
temporary virtual environment. It runs from outside the source checkout, clears
Python import-path overrides, and verifies that imports come from the installed
package. Checks cover the public API, installed `py.typed` marker, console and
module commands, JSON and CSV exports, saved-report comparison, and spawned
workers. Temporary build and test files are cleaned up when the check finishes.
Building requires access to the build dependencies declared in `pyproject.toml`,
either from the package index or a configured local cache.

The suite includes doctests, small-input correctness checks, boundary and
duplicate cases, seeded larger-input checks against `bisect`, multiprocessing
failures, benchmark validation, and CLI/export/compare coverage. CI is configured
to run tests and installed-wheel verification on Windows and Linux across Python
3.10 through 3.14, enforce the coverage floor, publish each coverage report as an
artifact, and check lint, formatting, and strict types in a separate job.
Dependabot checks GitHub Actions and Python development dependencies weekly.

The implementation is split by responsibility:

```text
search_algos/
    algorithms.py   Pure search functions
    timing.py       Optional timing and profiling helpers
    parallel.py     Partitioning and process orchestration
    benchmarks.py   Workload generation, measurement, and validation
    comparison.py   Saved-report matching and descriptive comparisons
    measurement.py  GC policy around timed regions
    metadata.py     Runtime and source provenance
    validation.py   Shared argument validators
    cli.py          Argument parsing and report output
    __init__.py     Public API exports
    __main__.py     python -m search_algos entry point
search_algos.py     Compatibility launcher for repository checkouts
tests/              Standard-library unittest suite
scripts/
    verify_release.py  Build and test an installed wheel outside the checkout
```

This project is distributed under GPL-3.0-only. See [LICENSE](LICENSE).
