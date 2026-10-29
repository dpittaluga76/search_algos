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

The default run uses 1,000 elements, all four dataset distributions, the six
sequential algorithms, 100 queries per batch, one warmup batch, seven measured
batches, and seed 0. Multiprocessing is opt-in because process startup usually
costs much more than a single binary search.

## Command-line options

| Option | Meaning | Default |
| --- | --- | --- |
| `--size`, `--sizes` | One or more nonnegative dataset sizes | `1000` |
| `--datasets` | One or more of `uniform`, `gapped`, `duplicates`, `skewed` | All four |
| `--algorithms` | One or more of `linear`, `binary`, `bisect`, `recursive`, `interpolation`, `set`, `parallel`; use `all` alone for all seven | All except `parallel` |
| `--seed` | Integer random seed | `0` |
| `--repetitions` | Positive number of measured batches | `7` |
| `--warmups` | Nonnegative number of discarded warmup batches | `1` |
| `--queries` | Positive number of queries per batch | `100` |
| `--hit-rate` | Requested fraction of queries that find a value, from 0 to 1 | `0.5` |
| `--workers` | Positive worker count for multiprocessing | Available CPU count |
| `--format` | `text`, `json`, or `csv` | `text` |
| `--output` | Destination file; its parent directory must exist | Standard output |

Use `--help` for the full command reference. A zero-size dataset is valid and
has no successful queries, regardless of the requested hit rate. Other hit
counts are rounded to a whole number of queries. Worker counts are capped by
the number of elements, and by 61 on Windows.

Export a reproducible comparison:

```console
python -m search_algos --size 1000 10000 --datasets uniform duplicates skewed --seed 42 --format json --output results.json
python -m search_algos --size 1000 --datasets gapped --algorithms binary set --format csv --output results.csv
```

Include the full cost of multiprocessing:

```console
python -m search_algos --size 10000 --datasets gapped --algorithms binary parallel --workers 2 --queries 100 --repetitions 5
```

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
| `find_by_sets` | Iterable of hashable values and a hashable target | `True` or `False` |

Sorted-input requirements are preconditions: the functions do not sort or scan
the input to validate ordering, since that would change the cost being measured.
Use the two-argument recursive search API to let it manage its bounds. Explicit
`left` and `right` bounds remain available; `right` is inclusive and both bounds
must describe a valid search range. Within a bounded search, the result is the
first matching index in that range.

`find_by_sets` constructs a set on every call. For repeated membership checks,
construct the set once and use `target in prepared_set`. The benchmark measures
this preparation and the subsequent batch of membership queries separately.

The optional `show_runtime_and_result` and `profile_this` decorators remain
available from `search_algos`. They return the wrapped function's result; search functions
are not decorated automatically. Timing a recursive search therefore surrounds
the complete call once. Result formatting distinguishes indices, missing values,
and Boolean membership results.

## Multiprocessing API

`parallel_search` partitions a sorted sequence, searches every partition, and
returns the first matching index in the original sequence. `parallel_search_many`
performs a batch of queries with one process pool. Remainder elements are
included, and empty inputs do not start workers.

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

Set construction is timed separately on each repetition. The total cost combines
preparation and the lookup batch, making the query count relevant to how setup
cost is amortized. Multiprocessing lookup timings include partitioning, process
startup, serialization, result aggregation, and pool shutdown for each batch.
Pools are not retained between samples. Sequential lookups include the Python
loop that executes the queries.

Text output has one table per workload (size and dataset), ordered fastest to
slowest by total median time, including setup and lookup costs. Its `vs fastest`
column divides each total by the fastest total in the same table. JSON includes configuration, runtime metadata,
result summaries, and individual timing samples. CSV repeats metadata alongside
each result and encodes sample lists as JSON within cells. The schema version is
`1`; result records include:

| Field | Interpretation |
| --- | --- |
| `setup_median_ns` | Median set-construction cost; zero for other algorithms |
| `lookup_median_ns` | Median time for a complete batch of queries |
| `total_median_ns` | Median of each repetition's setup plus lookup time |
| `setup_iqr_ns`, `lookup_iqr_ns`, `total_iqr_ns` | Variability in each measured phase |
| `per_query_median_ns` | Median lookup batch time divided by query count |
| `setup_samples_ns`, `lookup_samples_ns` | Individual samples in nanoseconds |
| `timing_scope` | `lookup_batch` for sequential and set lookups; `batch_with_process_startup` for parallel lookups |
| `workload_id` | SHA-256 identifier of the sequence and queries |

Runtime metadata identifies the Python implementation/version and the platform
so results can be interpreted in context. Warmups and repeated measurements
reduce some noise, but CPU load, scheduling, caching, and machine differences
still affect results. Each repetition reuses the same workload.

## Development and verification

No third-party test dependencies are required:

```console
python -m unittest discover -s tests -v
```

The suite includes doctests, small-input correctness checks, boundary and
duplicate cases, multiprocessing failures, benchmark validation, and CLI/export
coverage. CI is configured to install the package and run the suite on Windows
and Linux across Python 3.10 through 3.14, followed by command-line smoke tests.

The implementation is split by responsibility:

```text
search_algos/
    algorithms.py   Pure search functions
    timing.py       Optional timing and profiling helpers
    parallel.py     Partitioning and process orchestration
    benchmarks.py   Workload generation, measurement, and validation
    cli.py          Argument parsing and report output
    __init__.py     Public API exports
    __main__.py     python -m search_algos entry point
search_algos.py     Compatibility launcher for repository checkouts
tests/              Standard-library unittest suite
```

This project is distributed under GPL-3.0-only. See [LICENSE](LICENSE).
