"""Scoped control of cyclic garbage collection during measurements."""

import gc
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def gc_policy(disabled: bool) -> Iterator[None]:
    """Apply the requested policy, restoring the caller's state even on error."""
    was_enabled = gc.isenabled()
    if disabled:
        gc.disable()
    else:
        gc.enable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
