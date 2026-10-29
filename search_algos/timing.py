"""Optional display/profiling helpers, separate from the search algorithms."""

import cProfile
from functools import wraps
from time import perf_counter


def format_result(result: int | bool | None) -> str:
    """Describe an index search or a Boolean membership result accurately."""
    if isinstance(result, bool):
        return "present" if result else "absent"
    if result is None:
        return "not found"
    return f"found at index {result}"


def show_runtime_and_result(func):
    """Time one complete call, print its result, and preserve its return value."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = perf_counter()
        result = func(*args, **kwargs)
        elapsed = perf_counter() - start
        print(f"{func.__name__}: {format_result(result)}; elapsed {elapsed:.9f} s")
        return result

    return wrapper


def profile_this(func):
    """Profile one complete call, restoring profiler state even on failure."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            return func(*args, **kwargs)
        finally:
            profiler.disable()
            profiler.print_stats()

    return wrapper
