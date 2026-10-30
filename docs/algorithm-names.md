# Algorithm names and terminology

Reviewed on 2026-10-30 against the implementations and the primary sources linked
below. This covers all 27 benchmark entries and their public search APIs.

The family identifications below are conclusions from comparing our code with
those sources. An **established family** does not imply an identical implementation
or duplicate-result contract. A **variant** adds an implementation choice to an
established family. A **project hybrid** is a descriptive label for this repo's
combination, wrapper, or selection rule; it is not a claim that the complete
implementation has a canonical published name. **Execution modes** describe
process orchestration and timing rather than additional search algorithms.

Public function names and benchmark identifiers are stable compatibility names
under [AGENTS.md](../AGENTS.md). Use the full names below in explanations and
comparisons. All first-index searches preserve the earliest duplicate position
and return `None` for a miss; `set` and `binary_slicing` return membership Booleans.

Benchmark and saved-report comparison output use concise descriptive labels from
`search_algos.naming`. Text shows `Label [identifier]`; JSON and CSV retain the
stable `algorithm` field and add `algorithm_label`. Matching never uses the label,
so older reports without labels and reports with older labels remain comparable.
The full descriptions below explain the concise display names.

The default selection contains 23 entries, including all eight additional
searches. Plain `linear`, `certified_radix`, `parallel`, and `parallel_warm` are
opt-in. `--algorithms all` includes every one of the 27 identifiers below.

## Complete naming audit

| Benchmark identifier | Public API | Full name to use | Assessment and source |
| --- | --- | --- | --- |
| `linear` | `linear_search` | Linear search (sequential search) | Established family; checks values in order. [NIST][linear]. |
| `binary` | `binary_search` | Binary search for the lower bound, with equality verification | Binary-search variant that locates the first match. [NIST][binary], [Python][bisect]. |
| `bisect` | `binary_search_std_lib` | Binary search using Python's `bisect_left` | Standard-library implementation variant, with an equality check after the insertion-point lookup. [Python][bisect]. |
| `recursive` | `binary_search_by_recursion` | Recursive binary search for the first match | Implementation variant; the short identifier alone omits the binary-search family. [NIST][binary]. |
| `interpolation` | `interpolation_search` | Interpolation search with numeric safeguards | Established family; predicts positions from endpoint values. Unsafe arithmetic can trigger binary search. [NIST][interpolation]. |
| `interpolation_hybrid` | `interpolation_search_hybrid` | Budgeted interpolation–binary search hybrid | Project hybrid: at most `n.bit_length()` interpolation probes, then bounded binary search. Related hybrids exist, but their switching rules differ; see [Waterloo][introspective]. |
| `exponential` | `exponential_search` | Exponential search followed by binary search | Established family; doubles the bound and binary-searches the resulting interval. [TheAlgorithms][exponential]. |
| `jump` | `jump_search` | Jump search (block search) | Established family; square-root jumps followed by a linear block scan. [NIST][jump]. |
| `set` | `find_by_sets` | Hash-set membership lookup | Established data-structure operation, not an ordered-array search. The benchmark prepares the set separately. [CPython implementation][set]. |
| `dict` | `build_first_index`, `find_by_dict` | Hash-table lookup in a first-occurrence index | Established data-structure operation; values map to their first positions. The benchmark builds the dictionary separately. [Python FAQ][dict]. |
| `radix` | `build_radix_index` | Radix Binary Search (RBS), using a flat radix directory | RBS-family variant: a prefix directory bounds the final binary search. Our construction uses boundary bisections instead of SOSD's scan. [SOSD paper][sosd], [reference implementation][rbs]. |
| `neighbor_prepared` | `build_neighbor_index` | Prepared interpolation prediction with neighbor checks and binary fallback | Project hybrid; one endpoint prediction and adjacent checks precede exact bounded bisection. Uses [interpolation][interpolation] and [binary-search][bisect] techniques. |
| `guarded_prepared` | `build_guarded_index` | Binary search with cached range guards | Project wrapper; stores endpoints, rejects outside targets, and uses full-range `bisect_left` otherwise. [Binary-search primitive][bisect]. |
| `adaptive_index` | `build_adaptive_index` | Heuristic selection among prepared lookup strategies | Project selector; samples choose a hash index, interpolation prediction, guarded bisection, or radix directory. No canonical external name is claimed for this exact rule. |
| `dict_reverse` | `build_first_index_reversed` | First-occurrence hash index built by reverse traversal | Construction variant of the same [hash-table family][dict]; lookup is ordinary dictionary lookup. It does not search queries backwards. |
| `landmark_index` | `build_landmark_index` | Adaptive stride/run/radix lookup hybrid | Project hybrid; selects verified-per-query stride prediction, a map of duplicate-run starts, or a radix directory. “Landmark” is a project identifier. |
| `certified_radix` | `build_certified_radix_index` | Radix index with verified arithmetic/bitmap shortcuts | Project hybrid; buckets use checked arithmetic progressions, bitmap membership plus rank, or bounded bisection. “Certified” describes verified local properties. |
| `parallel` | `parallel_search`, `parallel_search_many` | Range-routed binary search with a cold process pool | Execution mode using binary search by default; timing includes pool startup and shutdown. [Python process pools][pool]. |
| `parallel_warm` | `ParallelSearchPool.search_many` | Range-routed binary search with a reused process pool | Execution mode; workers are reused, while chunks and queries are still transferred for each batch. [Python process pools][pool]. |
| `fibonacci` | `fibonacci_search` | Fibonacci array search (Fibonaccian search) | Established family; narrows intervals using Fibonacci numbers. [NIST][fibonacci]. |
| `ternary` | `ternary_search` | Ternary search in a sorted array, with a small linear finish | Implementation variant of array lookup by thirds. This usage is documented by [GWU][ternary-array]. |
| `ternary_recursive` | `ternary_search_by_recursion` | Recursive ternary search in a sorted array, with a small linear finish | The same array-search family with recursive interval reduction. [GWU][ternary-array]. |
| `double_linear` | `double_linear_search` | Double-ended linear search for the first match | “Double linear search” is used by [TheAlgorithms][double-linear]. Our variant defers right-side results until earlier duplicates are excluded. |
| `double_linear_recursive` | `double_linear_search_by_recursion` | Recursive double-ended linear search for the first match | Implementation variant of the same two-ended scan, using bounded recursive batches. [Upstream recursive implementation][double-recursive]. |
| `sentinel` | `sentinel_linear_search`, `build_sentinel_search` | Sentinel linear search with a private buffer | Recognized linear-search variant. Our benchmark copies input once per batch and reuses the buffer. [TheAlgorithms][sentinel]. |
| `interpolation_recursive` | `interpolation_search_by_recursion` | Recursive interpolation search with numeric safeguards | Implementation variant of [interpolation search][interpolation]; bounded batches prevent linear stack growth without changing the probe strategy. |
| `binary_slicing` | `binary_search_slicing` | Recursive binary membership search using slices | Implementation variant of [binary search][binary]. Boolean results and slice-copying costs are explicit; no separate search-family name is claimed. |

The process APIs accept a custom `search_func`; the table describes the default
binary-search configuration used by the benchmarks. `multiproc_test` is a legacy
wrapper around `parallel_search`, not an additional algorithm.

Direct `find_by_sets`, `find_by_dict`, and `sentinel_linear_search` calls include
their construction or copying on every call. Their benchmark entries separate
that preparation from lookup, then reuse the prepared structure throughout a
query batch.

## Names needing particular care

### Radix Binary Search, rather than an unspecified “radix algorithm”

The [SOSD paper, Section 2][sosd] names an auxiliary prefix directory followed by
a binary search **RadixBinarySearch (RBS)**. The
[reference implementation][rbs] normalizes keys by subtracting the minimum and
shifts away low bits, as our implementation does. This supports classifying our
`radix` entry as an RBS variant. Its boundary-building method and exact
first-duplicate contract remain implementation details of this repo.

It operates on already sorted input and never rearranges values. It is not a
sorting routine. It also does not fit spline segments or build a radix tree:
SOSD distinguishes RBS, RadixSpline, and ART as separate structures. The
`certified_radix` and `landmark_index` combinations should retain their explicit
project-hybrid descriptions rather than adopting any of those other names.

### Ternary array search versus ternary optimization

“Ternary search” has more than one documented use.
[GWU's array-search example][ternary-array] searches an ordered array by thirds.
[CP-Algorithms][ternary-optimization] uses the term for finding an extremum of a
unimodal function. Our implementations do sorted-array value lookup, with a
small linear finish; **ternary array search** makes that meaning explicit.
They do not perform unimodal optimization.

### Hybrid labels describe the actual switching rule

[Waterloo's introspective search][introspective] alternates interpolation and
binary steps. Our `interpolation_hybrid` instead spends an interpolation-probe
budget before switching to binary search. Keeping the descriptive name
**budgeted interpolation–binary search hybrid** avoids implying that it is that
specific published implementation.

Likewise, `neighbor_prepared`, `guarded_prepared`, `adaptive_index`,
`certified_radix`, and `landmark_index` describe project-specific combinations,
caching, or strategy-selection rules. The code supports the descriptions in the
table; the external sources establish their component techniques. This review
does not claim either canonical names or novelty for those exact combinations.

### Double-ended scanning and process execution

Use **double-ended linear search** for the two-ended array scans. “Double linear”
has upstream precedent, but the full description better conveys the strategy
and its first-occurrence adaptation.

Use **cold/reused process-pool search** for `parallel` and `parallel_warm`.
These are two timing and execution modes of the underlying lookup. A reused
pool retains workers; it does not preload the input permanently into them.

## Maintenance rule

For future entries, identify the algorithm family from the implementation,
qualify changed contracts or switching rules, and cite a primary source. Mark
combinations without an established exact name as project hybrids. Preserve
public identifiers and report compatibility when improving descriptive labels.

[linear]: https://xlinux.nist.gov/dads/HTML/linearSearch.html
[binary]: https://xlinux.nist.gov/dads/HTML/binarySearch.html
[bisect]: https://docs.python.org/3.14/library/bisect.html
[interpolation]: https://xlinux.nist.gov/dads/HTML/interpolationSearch.html
[jump]: https://xlinux.nist.gov/dads/HTML/jumpsearch.html
[fibonacci]: https://xlinux.nist.gov/dads/HTML/fibonaccianSearch.html
[exponential]: https://github.com/TheAlgorithms/Python/blob/6e03a48579ca212a08b36be00378f887dc41a003/searches/exponential_search.py
[set]: https://github.com/python/cpython/blob/3.11/Objects/setobject.c
[dict]: https://docs.python.org/3.14/faq/design.html#how-are-dictionaries-implemented-in-cpython
[sosd]: https://arxiv.org/pdf/1911.13014
[rbs]: https://github.com/learnedsystems/SOSD/blob/master/competitors/radix_binary_search.h
[pool]: https://docs.python.org/3.14/library/concurrent.futures.html#processpoolexecutor
[ternary-array]: https://www2.seas.gwu.edu/~drum/cs1112/lectures/module7/suppl/index.html
[ternary-optimization]: https://cp-algorithms.com/num_methods/ternary_search.html
[introspective]: https://ece.uwaterloo.ca/~dwharder/aads/Algorithms/Searching/Introspective_search/
[double-linear]: https://github.com/TheAlgorithms/Python/blob/6e03a48579ca212a08b36be00378f887dc41a003/searches/double_linear_search.py
[double-recursive]: https://github.com/TheAlgorithms/Python/blob/6e03a48579ca212a08b36be00378f887dc41a003/searches/double_linear_search_recursion.py
[sentinel]: https://github.com/TheAlgorithms/Python/blob/6e03a48579ca212a08b36be00378f887dc41a003/searches/sentinel_linear_search.py
