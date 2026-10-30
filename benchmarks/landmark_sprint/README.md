# Landmark index: timed research sprint

`landmark_index` met the requested top-two target in the aggregate confirmation results. It ranked first on all three datasets in the initial default-seed run. Uniform and duplicate results were consistently strong in confirmation; gapped results were close and varied by run. No existing algorithm was replaced.

## What changed

Three exploration agents investigated preparation, prediction, and directories. A fresh team of three agents plus the parent combined the findings, tested exactness, integrated the CLI, and audited the results. The user extended the initial ten-minute sprint to allow confirmation measurements.

The new builder uses only the input values, never dataset labels or query targets:

- A sample of at most 16 adjacent pairs selects the preparation path.
- Duplicate-rich samples select a first-index hash map built by jumping over each run with `bisect_right`, instead of visiting every repeated value. A run-count budget limits the damage from misleading samples.
- Divisible endpoints enable an integer stride prediction. Equality and neighboring values verify every result; inaccurate predictions fall back to bounded bisect.
- Other inputs use a radix directory with at most 1,024 buckets. Endpoint guards permit removing a redundant lookup bound check while preserving exact equality checks.

Empty inputs, negative and arbitrarily large integers, variable duplicate runs, deceptive samples, and irregular arrays with divisible endpoints are covered by tests. Sorted integer input and unchanged data remain preconditions.

## Measurements

Environment: CPython 3.11.15, Windows, AMD Ryzen 5 7600. All times below include index preparation plus the 20,000-query batch on 100,000 values. Ranks compare completed first-index algorithms; membership-only `set` is separate. The existing linear work limit skips linear search. Every measured result is checked outside timing. Tests and agent benchmarks were stopped before the final timing runs. CPU affinity and clock frequency were not controlled.

The initial seed-0 report uses the exact default configuration of:

```console
python -m search_algos --size 100000 --datasets uniform gapped duplicates --queries 20000
```

[Default report](default-cli.txt), [default schema-2 JSON](default-cli.json), [initial study](results.json), and [confirmation study](confirmation.json) preserve individual samples and environment metadata. Source hashes identify the measured uncommitted implementation.

Newly generated studies fingerprint every Python source under `search_algos/`,
plus their study scripts and shared fingerprint helper. This includes all
algorithm implementations and shared measurement code, and automatically covers
new package modules. The `source_sha256` path-to-hash format stays the same;
historical artifacts retain their original source hashes.

### Initial requested workload

| Dataset | landmark total ms | Best previous strategy | Previous total ms | landmark rank |
| --- | ---: | --- | ---: | ---: |
| uniform | 2.357 | neighbor_prepared | 2.681 | 1 |
| gapped | 4.438 | radix | 4.699 | 1 |
| duplicates | 1.872 | adaptive_index | 3.378 | 1 |

The initial study also tested seeds 1, 2, and 42. Seed 42 placed third on uniform and gapped, with substantial timing variation. Those results are retained; the default run alone is not proof of a universal ranking.

### Confirmation

Each confirmation used 21 measured batches and three warmups, giving three complete rotations of the seven algorithms. Three separate runs per seed changed the initial algorithm order. Cyclic GC was disabled during timing. The cells below are medians of the three run medians; ranks use those aggregate values. A close numerical ranking is not a statistical significance result.

| Seed | Dataset | landmark total ms | Best previous strategy | Previous total ms | Aggregate rank | Individual ranks |
| ---: | --- | ---: | --- | ---: | ---: | --- |
| 0 | uniform | 2.367 | neighbor_prepared | 2.759 | 1 | 1, 1, 1 |
| 0 | gapped | 4.491 | adaptive_index | 4.488 | 2 | 1, 2, 3 |
| 0 | duplicates | 1.824 | adaptive_index | 3.496 | 1 | 1, 1, 1 |
| 42 | uniform | 2.268 | neighbor_prepared | 2.714 | 1 | 1, 1, 1 |
| 42 | gapped | 5.814 | radix | 5.771 | 2 | 2, 1, 2 |
| 42 | duplicates | 1.998 | dict_reverse | 3.613 | 1 | 1, 1, 1 |

Uniform and duplicates ranked first in every confirmation run. Gapped ranked first or second in five of six runs, and third in one. In particular, seed-0 gapped aggregate totals of about 4.491 ms versus 4.488 ms are effectively a tie at this measurement precision. The implementation cannot promise a top-two position on every machine or invocation.

### Independent workload checks

The initial study includes mixed-parity random keys, mixed-parity duplicate keys, mixed local regions, and same-parity missing keys. All misses in these extra workloads are inside the value range. These comparisons prevent the even-key/odd-miss pattern in the standard generator from being the sole explanation for a win. They use seed 0, one warmup, and seven measurements.

| Workload | landmark total ms | Rank among focused competitors |
| --- | ---: | ---: |
| mixed_duplicates | 1.561 | 1 |
| mixed_regions | 4.923 | 2 |
| mixed_uniform | 6.463 | 2 |
| same_parity_gaps | 5.282 | 1 |

## Novelty assessment

This is a new implementation and combination for this repository. Scientific novelty has not been established. The closest primary reference found in the brief review is [The Revenge of Interpolation Search, SIGMOD 2019](https://pages.cs.wisc.edu/~jignesh/publ/Revenge_of_the_Interpolation_Search.pdf), which discusses reusing interpolation slopes and sampling-based selection. [RadixSpline](https://arxiv.org/abs/2004.14541) establishes radix-assisted routing; [Python bisect documentation](https://docs.python.org/3.11/library/bisect.html) defines the right-bound primitive used to skip equal runs. The particular bounded preparation policy and combination would require a deeper literature review before any originality claim.

## Validation and reproduction

The complete suite passed 165 tests with 98% combined statement/branch coverage. Both new modules, `landmark.py` and the earlier `certified.py`, reached 100% statement and branch coverage. Ruff lint/format, strict mypy for Windows and Linux, and clean installed-wheel tests passed on the available Windows/Python 3.11 environment; the full multi-OS/Python CI matrix was not run locally.

```console
python -m scripts.benchmark_landmark
python -m scripts.confirm_landmark
```

The original exploration candidates are retained under `candidates/`. The paired-directory variant is unselected and was not used for the reported production measurements. The study metadata records the working tree before these changes were committed; it is historical provenance, not the current repository status.
