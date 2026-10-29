"""Small shared validators for workload and benchmark options."""

import math
from collections.abc import Sequence


def validate_integer(name: str, value: object, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def validate_number(name: str, value: object, maximum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite nonnegative number")
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        limit = f" between 0 and {maximum:g}" if maximum is not None else " >= 0"
        raise ValueError(f"{name} must be finite and{limit}")


def validate_selection(name: str, selected: Sequence[str], allowed: Sequence[str]) -> None:
    if (
        isinstance(selected, (str, bytes))
        or not selected
        or any(value not in allowed for value in selected)
    ):
        raise ValueError(f"{name} must be selected from {', '.join(allowed)}")
    if len(set(selected)) != len(selected):
        raise ValueError(f"{name} must not contain duplicates")


def validate_query_options(queries: int, hit_rate: float, seed: int) -> None:
    validate_integer("queries", queries, 1)
    validate_number("hit_rate", hit_rate, 1)
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
