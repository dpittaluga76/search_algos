# Preserve existing algorithms

Existing search algorithms are comparison baselines. Preserve their strategies,
public function names, and benchmark entries.

Implement performance experiments and alternative strategies under distinct
names. Do not replace an existing algorithm, redirect its name to a new strategy,
or remove a baseline to improve benchmark rankings.

Correctness fixes may update an existing algorithm while retaining its strategy
and documented contract. Add tests and documentation for new alternatives, and
measure preparation separately from lookup when they build an index.
