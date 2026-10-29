"""Quiet search functions and optional benchmarking utilities.

Index searches return the first matching index, or ``None``. Set lookup
returns a Boolean. Importing this package never starts workers or a benchmark.
"""

from .algorithms import (
    binary_search,
    binary_search_by_recursion,
    binary_search_std_lib,
    build_first_index,
    build_radix_index,
    exponential_search,
    find_by_dict,
    find_by_sets,
    interpolation_search,
    interpolation_search_hybrid,
    jump_search,
    linear_search,
)
from .parallel import ParallelSearchPool, multiproc_test, parallel_search, parallel_search_many
from .timing import profile_this, show_runtime_and_result

__all__ = [
    "linear_search",
    "binary_search",
    "binary_search_std_lib",
    "binary_search_by_recursion",
    "interpolation_search",
    "find_by_sets",
    "parallel_search",
    "parallel_search_many",
    "multiproc_test",
    "profile_this",
    "show_runtime_and_result",
    "build_first_index",
    "build_radix_index",
    "find_by_dict",
    "exponential_search",
    "jump_search",
    "interpolation_search_hybrid",
    "ParallelSearchPool",
]
