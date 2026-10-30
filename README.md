# Search algorithms benchmark with Python

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

The default run uses 1,000 elements, four dataset distributions, 23 sequential
benchmark entries, 100 queries per batch, one warmup batch, seven measured batches, and
seed 0. Cyclic garbage collection is disabled during measurements. The radix
directory and `neighbor_prepared`, `dict_reverse`, `guarded_prepared`,
`adaptive_index`, and `landmark_index` are included in the default comparisons.
Plain `linear`, `certified_radix`, both multiprocessing modes, and the adversarial
dataset are opt-in.
Process startup usually costs much more than a single binary search.
The eight additional search entries are included by default: Fibonacci,
iterative and recursive ternary, iterative and recursive double linear, sentinel linear, recursive
interpolation, and slicing binary membership. Use `--algorithms all` to select all
27 entries, including multiprocessing.

## BISECT

Python's `bisect` module provides binary search for already sorted sequences.
Its search functions take O(log n) comparisons without changing the input.
`bisect_left(values, target)` returns the position before any equal values;
`bisect_right` (also called `bisect`) returns the position after them. A returned
position can be `len(values)`, meaning insertion at the end. See the
[Python bisect documentation](https://docs.python.org/3/library/bisect.html).

The search starts with `lo = 0` and `hi = len(values)`. The interval `[lo, hi)`
contains the elements still to probe: `lo` is included and `hi` is excluded.
At each step, `mid = (lo + hi) // 2`:

- If `values[mid] < target`, move `lo` to `mid + 1`.
- Otherwise, move `hi` to `mid`. The insertion position is at or before `mid`;
  `mid` can still be the answer even though that element leaves the probe window.

When `lo == hi`, that boundary is the insertion position. This does not establish
that the target exists. The CLI's `bisect` algorithm calls
`binary_search_std_lib`, which checks the boundary and equality to return the
first matching index or `None`:

```python
from bisect import bisect_left


def binary_search_std_lib(input_list, lookup_value):
    index = bisect_left(input_list, lookup_value)
    if index < len(input_list) and input_list[index] == lookup_value:
        return index
    return None
```

### Interactive example

[Open the bisect walkthrough](https://search-lab-python.dpittaluga.chatgpt.site/#/examples/bisect-left)
in Search Lab, with step controls, playback, custom targets, synchronized Python
code highlighting, and a copyable Python example. The public example library
includes both bisect and radix.

Search Lab simulates the Python call in the browser. Its sorted input is:

```python
values = [2, 5, 7, 7, 7, 11, 14, 18, 21, 25, 30, 33]
```

| Target | `bisect_left(values, target)` | `binary_search_std_lib(values, target)` |
| --- | --- | --- |
| `7` | `2` | `2` (first duplicate) |
| `18` | `7` | `7` |
| `9` | `5` | `None` |
| `40` | `12` | `None` |
| `1` | `0` | `None` |

## RADIX

The CLI's `radix` strategy uses `build_radix_index` to prepare a directory of
value ranges for repeated searches on an already sorted integer sequence.
It leaves the input in place.

1. **Prepare the directory.** Divide the value range into buckets whose width
   is a power of two. Use `bisect_left` to record each bucket's start and end
   indices. Equal values stay in the same bucket.
2. **Route a target.** Reject values outside the input range. Otherwise, subtract
   the minimum value and apply a bit shift to calculate the target's bucket.
3. **Search that bucket.** Call `bisect_left` between the stored offsets, then
   check the boundary and equality to return the first matching index or `None`.

Queries reuse the directory, so preparation and lookup have separate costs.
Smaller search windows can help with repeated lookups, while short batches,
skewed distributions, or outliers may make radix slower than full-range bisect.
Keep the indexed sequence unchanged during reuse. See [Search API](#search-api)
for the configuration, complexity, and input requirements.

### Interactive example

[Open the radix walkthrough](https://search-lab-python.dpittaluga.chatgpt.site/#/examples/radix)
in Search Lab to step through directory preparation, target routing, and the
bounded bisect search. Switch between **Preparation** and **Lookup**, change the
directory bits, or try custom targets. Changing the target reuses the directory;
changing the bit setting rebuilds it. Playback, code highlighting, and a
copyable Python example are included, as in the bisect walkthrough.

The browser simulation starts with this sequence and `bits=3` for readability;
the package and CLI default to `bits=12`:

```python
from search_algos import build_radix_index

values = [-12, -8, -8, -7, 4, 4, 5, 12, 13, 20, 23, 23]
lookup = build_radix_index(values, bits=3)
```

At three bits, the bucket width is eight integers and the directory offsets are
`[0, 4, 4, 7, 9, 12]`. Target `4` selects bucket 2, whose value range is `[4, 12)`
and index window is `[4, 7)`. Target `0` selects the empty bucket 1, whose start
and end indices are both `4`.

| Target | `lookup(target)` | Case |
| --- | --- | --- |
| `4` | `4` | First duplicate |
| `-8` | `1` | Negative value, first duplicate |
| `0` | `None` | Empty bucket |
| `6` | `None` | Missing value within a nonempty bucket |
| `23` | `10` | Last value, first duplicate |
| `40` | `None` | Outside the input range; no bisect call |

## Command-line options

| Option | Meaning | Default |
| --- | --- | --- |
| `--size`, `--sizes` | One or more nonnegative dataset sizes | `1000` |
| `--datasets` | One or more of `uniform`, `gapped`, `duplicates`, `skewed`, `adversarial` | All except `adversarial` |
| `--algorithms` | One or more identifiers from the list below; use `all` alone for all 27 | 23 sequential entries, including all eight additional searches; plain `linear` is opt-in |
| `--seed` | Integer random seed | `0` |
| `--repetitions` | Positive number of measured batches | `7` |
| `--warmups` | Nonnegative number of discarded warmup batches | `1` |
| `--queries` | Positive number of queries per batch | `100` |
| `--hit-rate` | Requested fraction of queries that find a value, from 0 to 1 | `0.5` |
| `--workers` | Positive worker count for multiprocessing | Available CPU count |
| `--gc` | Cyclic GC policy during measurements: `enabled` or `disabled` | `disabled` |
| `--max-linear-work` | Skip `linear`, `double_linear`, `double_linear_recursive`, `sentinel`, and `binary_slicing` when `size × queries × (repetitions + warmups)` exceeds this limit; `0` disables the limit | `50000000` |
| `--time-budget` | Soft execution budget in seconds per algorithm/workload; `0` disables the budget | `5` |
| `--format` | `text`, `json`, or `csv` | `text` |
| `--output` | Destination file; its parent directory must exist | Standard output |
| `--color` | Text colors: `auto`, `always`, or `never` | `auto` |

Use `--help` for the full command reference. A zero-size dataset is valid and
has no successful queries, regardless of the requested hit rate. Other hit
counts are rounded to a whole number of queries. Worker counts are capped by
the number of elements, and by 61 on Windows. Algorithm names are `linear`,
`binary`, `bisect`, `recursive`, `interpolation`, `interpolation_hybrid`,
`exponential`, `jump`, `set`, `dict`, `radix`, `neighbor_prepared`, `dict_reverse`,
`guarded_prepared`, `adaptive_index`, `landmark_index`, `certified_radix`, `parallel`, and
`parallel_warm`, `fibonacci`, `ternary`, `ternary_recursive`, `double_linear`,
`double_linear_recursive`, `sentinel`, `interpolation_recursive`, and `binary_slicing`.
All eight additional searches are selected by default. Plain `linear`,
`certified_radix`, `parallel`, and `parallel_warm` are opt-in; select them
explicitly or use `--algorithms all`. Every existing identifier remains available.

The [algorithm naming guide](docs/algorithm-names.md) maps all 27 identifiers and
public APIs to established families or explicit project-variant descriptions,
with primary sources. In particular, `radix` is a **Radix Binary Search (RBS)
variant**: a flat radix directory followed by bounded binary search. It searches
already sorted data. `ternary` and `ternary_recursive` mean **ternary array
search**. The prepared hybrids have descriptive project names, and `parallel`
and `parallel_warm` denote process-pool execution modes. Function names and
benchmark identifiers remain stable for existing callers and saved reports.
Text tables show the descriptive label followed by the identifier in brackets,
for example `Radix Binary Search (RBS) [radix]`. JSON and CSV retain `algorithm`
as the identifier and add `algorithm_label` for the descriptive name. Saved-report
comparisons display the same labels and continue matching on the existing
identity fields; labels can change without breaking comparisons with old reports.

Text reports use cyan section headings, aligned timing columns, and green
highlights for the fastest completed rows in each comparable group. A `*` marks
those rows, including ties, so the distinction remains visible without color.
Skipped and incomplete rows appear in yellow with their explanations. Narrow
terminals automatically use stacked rows that retain the full algorithm names,
identifiers, and every metric; wider terminals use tables.

Both benchmark and `compare` commands accept `--color auto|always|never`.
The default colors supported interactive terminals, including Windows consoles.
Pipes and `--output` files are plain text by default. A nonempty
[`NO_COLOR`](https://no-color.org/) environment variable or `TERM=dumb` disables
automatic colors. `--color always` explicitly forces ANSI color, including in
text files or pipelines; `--color never` disables it. JSON and CSV never receive
presentation escape codes. Formatting runs after measurements and adds no runtime
dependencies.

```console
python -m search_algos --size 1000 --datasets uniform --algorithms binary bisect radix
python -m search_algos --color never
python -m search_algos compare baseline.json candidate.json --color always
```

In comparison reports, green speed ratios indicate a faster candidate, red a
slower one, and unchanged ratios remain neutral. These colors describe median
timings; they do not indicate statistical significance. IQR overlap, warnings,
and rows that cannot be compared remain visible.

The work limit prevents unexpectedly expensive linear scans and tuple slicing
before they start. It also applies to sentinel preparation and lookup together;
skipping the entry does not construct its buffer. Interpolation entries retain
their distribution-sensitive linear worst case and are controlled by the soft
time budget between batches.
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

Compare the radix directory with full-range bisection and a dictionary
on a larger batch of repeated queries:

```console
python -m search_algos --size 100000 --datasets uniform gapped duplicates --algorithms bisect radix dict --queries 20000 --seed 42
```

Radix construction appears under setup, and each query batch reuses that
directory. Compare lookup costs for an already-prepared index and total costs
when construction is part of your application. Short query batches may not
amortize the setup cost.

Run the 23 default sequential entries, including all eight additional searches,
without specifying `--algorithms`:

```console
python -m search_algos --size 100000 --datasets uniform gapped duplicates --queries 20000
```

The work cap may skip the default linear-cost variants at this size and query
count. Include the plain linear baseline explicitly when needed:

```console
python -m search_algos --size 1000 --algorithms linear binary radix
```

Compare the prepared alternatives with selected baselines across regular,
duplicate-heavy, and difficult distributions:

```console
python -m search_algos --size 100000 --datasets uniform gapped duplicates skewed adversarial --algorithms bisect dict radix neighbor_prepared dict_reverse guarded_prepared adaptive_index certified_radix landmark_index --queries 20000 --seed 42
```

The new names select separate strategies; the original `bisect`, `dict`,
`radix`, and interpolation algorithms remain available unchanged. These
alternatives combine established search and indexing techniques. Their speed
depends on the input distribution, query mix, setup amortization, and runtime;
they are not guaranteed to outperform a baseline.

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
JSON floating-point numbers must remain finite, including numbers in metadata
and configuration fields. A configured GC policy must be valid and agree with
each row's known policy; contradictory measurement conditions are rejected.

Rows match by workload identifier, algorithm, result kind, and timing scope.
If identical workloads appear under multiple scenario labels, dataset and size
disambiguate those rows without merging their samples. Conflicting known size
or query counts make a matched pair incomparable. For legacy reports that omit
per-row query counts, a count supplied in `config.queries` still participates in
that compatibility check.
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
| `fibonacci_search` | Sequence sorted in ascending order | First match using Fibonacci-sized intervals |
| `ternary_search` | Sequence sorted in ascending order | First match using thirds and a small linear finish |
| `ternary_search_by_recursion` | Sequence sorted in ascending order | First match using recursive thirds and a small linear finish |
| `double_linear_search` | Sequence of equality-comparable values; sorting is unnecessary | First match scanning from both ends |
| `double_linear_search_by_recursion` | Sequence of equality-comparable values; sorting is unnecessary | First match using recursive batches of a double-ended scan |
| `sentinel_linear_search` | Iterable of values with reflexive equality; sorting is unnecessary | First match using a sentinel in a fresh private copy |
| `build_sentinel_search` | Iterable of values with reflexive equality; sorting is unnecessary | Reusable lookup over a private shallow copy; first index or `None` |
| `interpolation_search_by_recursion` | Ascending, finite numeric values | First match using recursive interpolation batches and numeric safeguards |
| `binary_search_slicing` | Ascending sequence supporting slicing | Boolean membership using recursive slices |
| `find_by_sets` | Iterable of hashable values and a hashable target | `True` or `False` |
| `build_first_index` | Iterable of hashable values; sorting is unnecessary | Dictionary mapping each value to its first index |
| `find_by_dict` | Iterable of hashable values and a hashable target | First matching index, or `None`; builds an index for this call |
| `build_radix_index` | Ascending sorted integer sequence, unchanged while the index is in use; integer targets | Reusable callable returning the first matching index, or `None` |
| `build_landmark_index` | Ascending sorted integer sequence, unchanged during reuse; integer targets | Reusable callable choosing stride prediction, duplicate-run indexing, or a compact radix directory; returns the first index or `None` |
| `build_certified_radix_index` | Ascending sorted integer sequence, unchanged during reuse; integer targets | Reusable callable selecting exact representations per radix bucket, with a bounded bisection fallback |
| `build_neighbor_index` | Ascending sorted integer sequence, unchanged during reuse; integer targets | Reusable callable using one interpolation prediction, exact neighbor checks, and a bisection fallback |
| `build_first_index_reversed` | Iterable of hashable values; sorting is unnecessary | Dictionary mapping each value to its first index, constructed by traversing backwards |
| `build_guarded_index` | Ascending sorted integer sequence, unchanged during reuse; integer targets | Reusable callable rejecting out-of-range targets before full-range bisection |
| `build_adaptive_index` | Ascending sorted integer sequence, unchanged during reuse; integer targets | Reusable callable choosing one exact lookup strategy during preparation |

Sorted-input requirements are preconditions: the functions do not sort the input
or perform a separate ordering-validation pass. For nonconstant input,
`build_certified_radix_index` scans the values to verify the local properties
needed by its shortcuts; this preparation is included in its setup measurement.
This scan does not validate the sorted-integer input contract.
Numeric prepared builders determine emptiness from `len(values)`; a custom
sequence's Boolean conversion is not required and does not determine its size.
For custom objects, ordering must agree with equality: objects that tie under
sorting must compare equal with `==`. For records sorted by only one field,
search a corresponding sequence of keys, or use `linear_search` when matching
the complete object by equality.
Use the two-argument `binary_search_by_recursion` API to let it manage its bounds. Explicit
`left` and `right` bounds remain available; `right` is inclusive and both bounds
must describe a valid search range. Within a bounded search, the result is the
first matching index in that range. Boolean bounds are rejected.

### Additional search strategies

All eight entries live in `search_algos.alternatives` and are also exported from
`search_algos`. Each has a distinct name and benchmark entry. Their implementations
are adapted from TheAlgorithms/Python, with first-occurrence handling, quiet APIs,
Python 3.10-compatible types, and caller-owned input preservation.

| Benchmark name | Strategy and cost |
| --- | --- |
| `fibonacci` | Shrinks Fibonacci-sized intervals toward the first match. O(log n) comparisons and O(1) state for fixed-width arithmetic. Fibonacci numbers are computed locally per lookup, with no global cache or hidden warmup state. |
| `ternary` | Divides the candidate interval into thirds, then linearly scans fewer than ten elements. O(log n) comparisons and O(1) state. |
| `ternary_recursive` | The same thirds strategy with O(log n) recursive stack space and the same small linear finish. |
| `double_linear` | Scans from both ends. Right-side matches remain candidates until earlier duplicates are excluded. O(n) worst-case time and O(1) state; first-index semantics can remove the early-return advantage of a right-side hit. |
| `double_linear_recursive` | Recursively examines pairs from both ends, resuming after batches of at most 64 pairs. O(n) worst-case time and bounded recursive stack space. |
| `sentinel` | Copies the input once per batch into a private list, then appends/removes each query's sentinel. Preparation is O(n) time and space; lookup is O(n) worst-case time. The benchmark measures preparation separately and reuses the buffer across the batch. |
| `interpolation_recursive` | Uses recursive interpolation, resuming after batches of at most 64 probes. O(n) worst-case time and bounded recursive stack space. Unsafe floating-point arithmetic falls back to bounded bisection; slow progress continues interpolating. |
| `binary_slicing` | Boolean membership through recursive binary search with slices. O(log n) comparisons and stack depth, but O(n) worst-case copying time and extra space on lists/tuples. Slice creation remains inside the lookup timer. |

The bounded recursive batches preserve their strategies without changing Python's
process-wide recursion limit. Recursive helpers avoid reference cycles, releasing
their input references even with cyclic GC disabled during benchmarks.
Sorted numeric interpolation supports arbitrarily
large integers and finite floats, including a bisection fallback when mixed
numeric subtraction rounds a nonzero span to zero. Input preconditions are not
validated by an extra scan. Other than sentinel's private copy, the additions
require no preparation; their benchmark setup samples are zero.

Compare all eight with selected baselines:

```console
python -m search_algos --size 1000 --datasets uniform duplicates adversarial --algorithms binary set fibonacci ternary ternary_recursive double_linear double_linear_recursive sentinel interpolation_recursive binary_slicing --queries 20 --seed 42
```

`binary_slicing` joins `set` in the Boolean membership comparison group. The other
seven return first indices and join that comparison group. The two result kinds
have separate rankings, and every timed batch is checked for correctness.

The direct sentinel API includes its private copy on every call. For reuse:

```python
from search_algos import build_sentinel_search, sentinel_linear_search

values = [3, 1, 3]
assert sentinel_linear_search(values, 3) == 0
assert values == [3, 1, 3]
lookup = build_sentinel_search(iter(values))
assert lookup(1) == 1
assert lookup(9) is None
assert lookup(3) == 0
```

The reusable sentinel callable snapshots the container with a shallow copy.
Elements must remain unchanged, and equality must be reflexive. The sentinel is
removed even if equality raises an exception. Use the callable sequentially;
concurrent calls and reentry from equality methods are unsupported.

`find_by_sets` and `find_by_dict` construct their hash structures on every call.
For repeated lookups, construct the structure once and reuse it:

```python
from search_algos import build_first_index

index = build_first_index([3, 1, 3, 2])
assert index.get(3) == 0
assert index.get(9) is None
```

The benchmark's `set`, `dict`, `radix`, and prepared-alternative rows measure
construction or preparation separately from the subsequent query batch. Every
prepared alternative returns first indices, matching the other index-search
algorithms.

Build a radix directory once for repeated lookups on a static integer sequence:

```python
from search_algos import build_radix_index

values = (-5, 1, 3, 3, 8)
lookup = build_radix_index(values)
assert lookup(3) == 2
assert lookup(-5) == 0
assert lookup(4) is None
```

The directory partitions the value range into at most 4,096 buckets. Each
lookup calculates its bucket using subtraction and a bit shift, then calls
`bisect_left` within that bucket. Equal values share a bucket, preserving the
first matching index even with duplicates. Empty inputs, negative values, and
arbitrarily large integers are supported.

The optional `bits` argument defaults to `12` and accepts integers from `0` to
`12`, excluding Booleans. It caps the directory at `2**bits` buckets; `bits=0`
uses a single bucket. The benchmark uses the default. For fixed-width integers,
building `B` buckets takes O(B log n) time and O(B) extra storage, without copying
the input or scanning it to validate ordering or types. Sorted integer input
and integer targets are preconditions. Do not mutate the sequence while using
the returned callable; rebuild the index after changing it.

Lookup takes O(log(m + 1)) search steps for a bucket containing `m` values, with
O(log n) worst-case search time. A directory can reduce lookup work on large,
well-spread integer data, but setup may dominate short batches. Skewed data or
outliers can concentrate most values in one bucket and make radix slower than
full-range bisection. Including it in the default benchmark does not imply a
universal speedup guarantee.

### Landmark hybrid

`landmark_index` / `build_landmark_index` is a separate experimental hybrid,
included in the default CLI run while retaining every existing algorithm.
Preparation uses a small sample to choose one exact search strategy:

- Duplicate-rich samples select a dictionary built by recording a run's first
  index and using `bisect_right` to jump over its remaining duplicates.
- A positive integer stride suggested by the endpoints selects a cheap position
  prediction. Each query verifies the candidate and adjacent values, or falls
  back to bounded bisection; endpoint regularity is never assumed to prove the
  interior values are regularly spaced.
- Other inputs use a compact radix directory with 1,024 possible buckets and
  bounded C bisection.

After `max(128, 2*n // n.bit_length())` distinct runs, an incomplete run map is
discarded and preparation falls back to the directory. This bounds wasted
run-search comparisons asymptotically by O(n) for misleading samples. Selection
changes performance only. All branches preserve the first original index,
including variable duplicate runs, negative values, and arbitrary-size integers.
The sorted integer input must remain unchanged while the index is reused.
The stride path needs O(1) preparation; successful run indexing uses O(u log n)
comparisons and O(u) space for `u` distinct keys; directory preparation uses
O(B log n) comparisons and O(B) space for at most 1,024 buckets. Stride and
directory queries have O(log n) worst-case comparison cost; completed run maps
use expected constant-time dictionary lookup. Arbitrary-size integer arithmetic
and hashing add operand-size costs. Preparation is timed separately from lookup,
and both contribute to total time.

```python
from search_algos import build_landmark_index

lookup = build_landmark_index([-4, -4, 1, 9])
assert lookup(-4) == 0
assert lookup(2) is None
```

This is a new combination in this repository of established techniques, not a
claim of a new theoretical algorithm or a guaranteed ranking on other machines.

The [landmark benchmark study](benchmarks/landmark_sprint/README.md) records the
initial results, noisy runs, and longer confirmation measurements. For the
requested 100,000-value/20,000-query workload, the confirmation aggregate ranked
first on uniform and duplicates and second on gapped; individual gapped runs
varied. Reproduce both stages from the checkout:

```console
python -m scripts.benchmark_landmark
python -m scripts.confirm_landmark
```

### Certified radix buckets

`certified_radix` / `build_certified_radix_index` is an additional experimental
strategy. It uses the same radix partitioning rule as `radix`, then scans
nonconstant input to verify which exact representation can be used in each
bucket. Empty and constant input use constant-cost shortcuts.

| Bucket contents | Lookup |
| --- | --- |
| Empty | Return `None` |
| One distinct value, including a duplicate run | Compare once and return its first index |
| Distinct values form an arithmetic progression | Use integer division and remainder to check membership and calculate the distinct-key rank |
| Irregular values with `maximum - minimum + 1 <= 256` | Check a membership bit mask, then count preceding set bits to calculate rank |
| Other contents | Run `bisect_left` within the bucket |

Progressions are verified across all distinct values, rather than inferred
from the endpoints or a sample. Duplicate progressions and bitmap buckets keep
the original first index for each distinct value; a duplicate-free progression
can calculate its original index directly. Every mode returns the first
matching index, or `None` for an absent value. The source sequence stays in place.

```python
from search_algos import build_certified_radix_index

values = (20, 23, 23, 26)
lookup = build_certified_radix_index(values, bits=0)
assert lookup(23) == 1
assert lookup(24) is None
assert lookup(26) == 3
```

As with `build_radix_index`, `bits` defaults to `12` and accepts non-Boolean
integers from `0` through `12`; the directory contains at most `2**bits` buckets.
Empty inputs, negative values, and arbitrarily large integers are supported.
Sorted integer input and integer targets remain preconditions, and the sequence
must remain unchanged while the callable is in use.

For fixed-size integer arithmetic, preparation takes O(n + B) work and at most
O(B + u) peak extra space for `B` buckets and `u` distinct values. Preparation
temporarily collects the distinct values and their first indices for each
bucket; one bucket can contain all `n` distinct values. The completed index
discards those per-key lists for unique progressions and fallback buckets.
Fallback buckets retain only their metadata and bounds. Certified shortcuts
take bounded work per lookup; fallback lookup takes O(log(m + 1)) search steps
for a bucket with `m` values. Arbitrary-size Python integer arithmetic adds a
cost depending on operand size. Bitmap width is capped to avoid allocating a
bit for every integer across a large gap.

The full preparation scan can dominate short query batches, and additional
dispatch or arithmetic can outweigh the comparisons saved. Compare both lookup
and total times against `bisect`, `radix`, and the other prepared strategies.
This combines established indexing techniques; it makes no claim of theoretical
novelty or a universal speedup. The existing benchmark distributions use even
keys and odd misses, so also test mixed-parity inputs and absent values that
share the stored keys' parity before drawing broader performance conclusions.

The [certified radix benchmark study](benchmarks/certified_radix/README.md)
documents the comparison and its methodology. Reproduce it from the checkout:

```console
python -m scripts.benchmark_certified --output benchmarks/certified_radix/results.json
```

The four original prepared alternatives also expose reusable lookup APIs:

```python
from search_algos import (
    build_adaptive_index,
    build_first_index_reversed,
    build_guarded_index,
    build_neighbor_index,
)

values = (-5, 1, 3, 3, 8)
for prepare in (build_neighbor_index, build_guarded_index, build_adaptive_index):
    lookup = prepare(values)
    assert lookup(3) == 2
    assert lookup(-5) == 0
    assert lookup(4) is None

index = build_first_index_reversed(iter([3, 1, 3, 2]))
assert index.get(3) == 0
assert index.get(9) is None
```

- **`neighbor_prepared` / `build_neighbor_index`:** caches the sequence length,
  endpoints, and value span. Each query makes one interpolation prediction,
  checks the predicted value and its neighbor to establish an exact first match
  or gap, and otherwise runs `bisect_left` over the remaining valid interval.
  Preparation and extra state are O(1); worst-case lookup is O(log n) for
  fixed-width integers. Even spacing can make the prediction useful, while
  irregular spacing can add overhead before the fallback.
- **`dict_reverse` / `build_first_index_reversed`:** constructs a dictionary
  from reversed values paired with descending positions. Repeated assignments
  leave the earliest position for each key. Construction is expected O(n), and
  the dictionary stores O(u) entries for `u` distinct keys. Non-sequence
  iterables are materialized once, temporarily using O(n) extra space. This is
  a separate API from `build_first_index`: dictionary insertion order follows
  reverse last-occurrence order, and equal keys retain the key object from the
  last occurrence, even though their stored index refers to the first occurrence.
- **`guarded_prepared` / `build_guarded_index`:** caches the sequence length and
  endpoints, rejects targets below the minimum or above the maximum, and uses
  full-range `bisect_left` for the remaining queries. Preparation and extra
  state are O(1); in-range lookup is O(log n). Range checks can help when many
  queries fall outside the data but add work to in-range queries.
- **`adaptive_index` / `build_adaptive_index`:** samples at most 16 positions
  across the sequence, including the final position and excluding the first.
  It counts matches between each sampled value and its immediate predecessor,
  and measures the sampled rank error of an endpoint-based interpolation model.
  More than half duplicate samples select the reversed dictionary; otherwise,
  maximum rank error at most one selects the neighbor strategy, error greater
  than one quarter of the final index selects guarded bisection, and the
  remaining cases select the radix directory. Empty and constant sequences use
  direct exact lookups. Preparation includes sampling and building the selected
  index; memory and lookup costs follow that strategy.

These numeric factories require sorted integer values and integer targets. They
do not scan or copy the sequence to validate these preconditions, and the
sequence must remain unchanged during reuse. Adaptive selection can build a
dictionary, which does traverse the input as part of construction. Sampling
chooses an implementation, not a correctness assumption: each selected lookup
still verifies exact matches and preserves the first duplicate index. The fixed
sampling rule can choose a slower strategy on unrepresentative samples; compare
the separate alternatives when tuning a workload.

Plain interpolation remains available to demonstrate distribution-sensitive
performance. The hybrid attempts at most `len(input_list).bit_length()`
interpolation probes before searching the remaining interval with binary search.
Both interpolation variants also fall back to bounded binary search when numeric
arithmetic overflows or a mixed integer/float span rounds to zero.

The optional `show_runtime_and_result` and `profile_this` decorators remain
available from `search_algos`. They return the wrapped function's result; search functions
are not decorated automatically. Timing a recursive search therefore surrounds
the complete call once. Result formatting distinguishes indices, missing values,
and Boolean membership results.
If another profiler is already active, `profile_this` leaves that session intact
and delegates statistics and reporting to its owner.

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
Ordinary containers such as lists and tuples transfer native slices. Other
sequence containers, including `deque` and `memoryview`, transfer indexed chunks
as plain lists. The input container itself need not be pickleable in that case;
transferred elements, targets, and custom search functions must be pickleable.

The legacy `multiproc_test(func, lst_size, seq, tgt, cpu_cnt)` entry point remains
available and now returns a global index or `None`. It rejects a `lst_size` that
does not match the sequence. The unused `multiproc_gensample` helper and
algorithm-level queue parameters have been removed; use the multiprocessing API
instead.

## Workloads and interpretation

All algorithms in a comparison receive the same sequence and queries. Dataset
generation, sorting, expected-result calculation, and correctness verification
are outside the lookup timer.

Index searches locate the first occurrence of a value; set lookup and slicing
binary search answer whether the value is present. The exported `result_kind` field identifies these
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

Set construction, sentinel buffer copying, and every prepared index are timed separately on every warmup
and measured repetition. This includes cached bounds, neighbor-search state,
reverse dictionary construction, and adaptive sampling plus the selected index
construction. The same prepared lookup is reused throughout its batch. Total
cost combines per-batch preparation and lookup, making the query count relevant
to how construction cost is amortized. Small batches may be slower overall even
when prepared lookup is faster. Sequential lookups include the Python loop that
executes the queries.

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
| `algorithm` | Stable benchmark identifier used for CLI selection and report matching |
| `algorithm_label` | Descriptive display name; presentation metadata, excluded from row identity |
| `status`, `reason` | `complete`, `incomplete`, or `skipped`, plus an explanation when work was limited |
| `repetitions_completed`, `warmups_completed` | Number of completed measured and warmup batches |
| `setup_median_ns` | Median per-batch set construction or index preparation cost; zero for unprepared searches |
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
Source-checkout version detection supports inline comments and indentation in
the static `[project]` metadata, so those formatting choices preserve provenance.
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

`python scripts/verify_release.py` builds a source distribution, then builds its
wheel from that archive and installs it into a fresh temporary virtual environment.
It checks that the archive includes the compatibility launcher, complete test
sources, study scripts, and release verifier. It runs from outside the source
checkout, clears Python import-path overrides, and verifies that imports come
from the installed package. Checks cover the public API, installed `py.typed` marker, console and
module commands, the shipped compatibility launcher with all algorithms, JSON
and CSV exports, saved-report comparison, and spawned workers. Temporary build
and test files are cleaned up when the check finishes. Building requires access
to the `build` frontend and dependencies declared in `pyproject.toml`, either
from the package index or a configured local cache. Build tools are installed in
a temporary builder environment; they are not runtime dependencies.

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
    algorithms.py   Original pure search functions
    alternatives.py Eight additional default searches and sentinel preparation
    naming.py       Descriptive labels for stable benchmark identifiers
    console.py      Terminal colors and responsive text layouts
    certified.py    Certified local representations behind a radix directory
    landmark.py     Stride, duplicate-run, and compact-directory hybrid
    prepared.py     Separate prepared search alternatives and adaptive selection
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
    benchmark_certified.py  Reproduce the certified radix comparison study
    verify_release.py  Build and test an installed wheel outside the checkout
```

This project is distributed under the MIT license. See [LICENSE](LICENSE), which
includes the project copyright and the upstream MIT copyright and permission notice.

The additional searches are adapted from
[TheAlgorithms/Python searches](https://github.com/TheAlgorithms/Python/tree/6e03a48579ca212a08b36be00378f887dc41a003/searches)
at commit `6e03a48579ca212a08b36be00378f887dc41a003`:

- `fibonacci_search.py`
- `ternary_search.py` (iterative and recursive)
- `double_linear_search.py` and `double_linear_search_recursion.py`
- `sentinel_linear_search.py`
- `interpolation_search.py` (recursive variant)
- `simple_binary_search.py` (Boolean slicing variant)

Their upstream notice is Copyright (c) 2016-2022 TheAlgorithms and contributors.
