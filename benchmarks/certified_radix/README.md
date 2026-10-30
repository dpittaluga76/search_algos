# Certified radix benchmark study

The initial `certified_radix` implementation is correct, but it does not improve
total time over the strongest existing strategies in this study. Its full
preparation scan is expensive, and its local shortcuts do not consistently beat
the existing C-backed bisection inside a radix bucket. It remains an opt-in
experimental strategy; every existing algorithm and the default selection are
preserved.

## Reproduction and measurement

From the repository root, run:

```console
python -m scripts.benchmark_certified --output benchmarks/certified_radix/results.json
```

For a regular CLI comparison, without the additional custom workloads:

```console
python -m search_algos --size 100000 --datasets uniform gapped duplicates skewed adversarial --algorithms bisect dict radix neighbor_prepared dict_reverse guarded_prepared adaptive_index certified_radix --queries 20000 --repetitions 7 --warmups 1 --seed 0
```

The recorded run on 2026-10-29 used CPython 3.11.15 on Windows, an AMD Ryzen 5
7600 processor, and the uncommitted source based on
`1dfe97ec47ae951dd562603bddb36627a9595233`. [Raw results](results.json) include
environment metadata, source SHA-256 hashes, workload identifiers, and individual
setup and lookup samples. The study JSON is a separate container format: each
entry in `cli_reports` is a normal schema-2 CLI report, while custom workloads
and allocation measurements have their own sections.

The main comparisons use 100,000 values, 20,000 queries, 50% hits, seeds 0/1/2,
one warmup, seven measured batches, and cyclic GC disabled during timing. Each
prepared index is rebuilt for every batch. Algorithm order rotates between
batches. First-index results are checked exactly outside timing; `set` results
are checked for membership.
Benchmarks ran after the tests and wheel checks, without concurrent agent test
runs. These are measurements on one desktop, without CPU pinning or locked CPU
frequency; small differences should not be treated as established rankings.

The first seed includes all fifteen existing sequential entries plus
`certified_radix` on uniform, gapped, and duplicate data. Linear search is
explicitly skipped by the existing work limit. All other rows complete all seven
repetitions. Multiprocessing is outside this sequential study. `set` is measured
but is not a first-index competitor because it returns membership only.

## Main workload results

Times below are milliseconds per batch, including preparation. Each cell is the
median of the three seeds' per-seed medians. The underlying total samples are
paired setup-plus-lookup measurements, not sums of independent medians.

| Dataset | bisect | radix | dict_reverse | neighbor_prepared | adaptive_index | certified_radix |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| uniform | 5.666 | 4.570 | 6.545 | 2.889 | 2.846 | 18.606 |
| gapped | 7.690 | 7.037 | 12.216 | 9.136 | 6.592 | 24.785 |
| duplicates | 6.153 | 4.387 | 3.717 | 7.288 | 3.553 | 8.229 |
| skewed | 5.739 | 5.849 | 10.686 | 9.646 | 5.234 | 19.747 |
| adversarial | 7.056 | 7.975 | 8.786 | 8.234 | 5.458 | 23.041 |

The new strategy's preparation and lookup measurements explain the tradeoff:

| Dataset | certified setup | certified lookup | certified total |
| --- | ---: | ---: | ---: |
| uniform | 14.695 | 4.197 | 18.606 |
| gapped | 16.289 | 7.608 | 24.785 |
| duplicates | 4.679 | 3.589 | 8.229 |
| skewed | 13.630 | 6.473 | 19.747 |
| adversarial | 19.057 | 3.984 | 23.041 |

These three columns aggregate medians separately, so setup plus lookup need not
equal the total column. Lookup alone improves over full-range bisect on some
datasets, but not sufficiently to recover preparation at 20,000 queries. On
uniform data, the existing neighbor strategy obtains a similar mathematical
shortcut with constant-cost preparation. On wide irregular buckets, certified
radix still has to bisect after paying for the scan and dispatch.

## Every sequential baseline, seed 0

This table retains the original strategies, including the slower ones. These
are single-seed totals and therefore differ from the three-seed table above.

| Algorithm | uniform ms | gapped ms | duplicates ms |
| --- | ---: | ---: | ---: |
| linear | skipped | skipped | skipped |
| binary | 24.663 | 22.947 | 23.149 |
| bisect | 5.494 | 6.155 | 6.153 |
| recursive | 40.550 | 39.118 | 39.737 |
| interpolation | 6.792 | 20.129 | 43.958 |
| interpolation_hybrid | 12.384 | 23.529 | 45.995 |
| exponential | 15.094 | 15.353 | 15.952 |
| jump | 332.789 | 360.232 | 348.824 |
| dict | 8.591 | 10.396 | 5.423 |
| radix | 4.552 | 4.812 | 4.387 |
| neighbor_prepared | 2.764 | 7.824 | 6.658 |
| guarded_prepared | 4.785 | 5.086 | 4.947 |
| adaptive_index | 2.846 | 4.717 | 3.553 |
| dict_reverse | 6.545 | 8.313 | 3.577 |
| certified_radix | 20.237 | 18.227 | 7.886 |

The membership-only `set` totals were 2.854, 4.823, and 2.342 ms respectively.
They cannot replace a first-index result.

## Removing the even-key / odd-miss shortcut

The CLI datasets are unchanged. Additional workloads in the study script use
the same timing, rotation, GC, and correctness machinery, with 50% hits and all
misses inside the stored value range:

- `mixed_uniform`: distinct integer keys sampled across a range containing both
  parities, rather than an arithmetic progression.
- `mixed_duplicates`: repeated keys sampled from a sparse, mixed-parity key set.
- `mixed_regions`: regions of arithmetic progressions, irregular compact keys,
  constant runs, and irregular duplicate runs.
- `same_parity_gaps`: both stored keys and absent query values are even.

The total milliseconds below use the same three-seed aggregation. Comparisons
are within each workload; its miss distribution differs from the regular CLI
workloads, where half of the misses are outside the range.

| Dataset | bisect | radix | dict_reverse | adaptive_index | certified_radix |
| --- | ---: | ---: | ---: | ---: | ---: |
| mixed_uniform | 7.240 | 5.910 | 8.792 | 5.742 | 21.853 |
| mixed_duplicates | 5.665 | 4.463 | 2.732 | 3.024 | 7.985 |
| mixed_regions | 7.206 | 5.339 | 5.600 | 5.332 | 15.917 |
| same_parity_gaps | 6.404 | 5.402 | 8.890 | 5.443 | 18.247 |

The local representations preserve correct results beyond the CLI's parity
pattern, but this run does not show a total-time advantage on these workloads.

## Query count and memory

The sensitivity runs retain 100,000 values and use seed 0 only. Times include
one new index build per query batch.

| Queries | Dataset | bisect ms | radix ms | dict_reverse ms | certified_radix ms |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1,000 | uniform | 0.361 | 1.214 | 7.427 | 15.508 |
| 1,000 | gapped | 0.298 | 1.315 | 7.941 | 13.395 |
| 1,000 | duplicates | 0.340 | 0.810 | 2.870 | 4.401 |
| 200,000 | uniform | 61.256 | 42.636 | 22.277 | 62.983 |
| 200,000 | gapped | 64.173 | 41.358 | 19.100 | 67.164 |
| 200,000 | duplicates | 62.821 | 42.648 | 12.308 | 42.406 |

At 200,000 duplicate queries, certified radix is about 1.48 times faster than
bisect in total, but `dict_reverse` is about 3.45 times faster than certified
radix. The near-tie with ordinary radix is not evidence of a reliable win.

Incremental retained Python allocations, in KiB, were measured with
`tracemalloc` after all timing runs, using seed 0. Input and query storage are
excluded; these figures are not process RSS or hardware-cache measurements.
Peak allocation figures are also retained in the JSON.

| Dataset | radix | dict | dict_reverse | certified_radix |
| --- | ---: | ---: | ---: | ---: |
| mixed_uniform | 111.3 | 7,847.5 | 8,237.2 | 440.3 |
| mixed_duplicates | 111.2 | 280.5 | 300.1 | 545.2 |
| mixed_regions | 111.3 | 4,010.2 | 4,217.5 | 1,512.5 |
| same_parity_gaps | 139.5 | 7,847.5 | 8,237.2 | 550.5 |

Certified radix uses less retained memory than dictionaries on the mostly
unique workloads, but more than ordinary radix in every measured case. It also
uses more than dictionaries on the highly duplicated workload. Future work
should measure whether reducing preparation and dispatch costs changes these
tradeoffs; these results do not justify promoting it into the default selection.
