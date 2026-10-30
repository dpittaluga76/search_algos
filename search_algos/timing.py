"""Optional display/profiling helpers, separate from the search algorithms."""

import cProfile
import sys
from collections.abc import Callable
from functools import wraps
from time import perf_counter
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")
SearchResult = TypeVar("SearchResult", bound=int | None)


def format_result(result: int | bool | None) -> str:
    """Describe an index search or a Boolean membership result accurately."""
    if isinstance(result, bool):
        return "present" if result else "absent"
    if result is None:
        return "not found"
    return f"found at index {result}"


def show_runtime_and_result(func: Callable[P, SearchResult]) -> Callable[P, SearchResult]:
    """Time one complete call, print its result, and preserve its return value."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> SearchResult:
        start = perf_counter()
        result = func(*args, **kwargs)
        elapsed = perf_counter() - start
        print(f"{func.__name__}: {format_result(result)}; elapsed {elapsed:.9f} s")
        return result

    return wrapper


def profile_this(func: Callable[P, R]) -> Callable[P, R]:
    """Profile a complete call without replacing an existing profiling session.

    If a profiler is already active, execute the function under that profiler
    and leave its statistics/reporting to its owner. Otherwise print this call's
    profile and disable the temporary profiler even when the function raises.
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        if sys.getprofile() is not None:
            return func(*args, **kwargs)
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            return func(*args, **kwargs)
        finally:
            profiler.disable()
            profiler.print_stats()

    return wrapper
