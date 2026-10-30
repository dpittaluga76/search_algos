"""Complete, deterministic source fingerprints for checkout-only studies."""

import hashlib
from pathlib import Path


def source_fingerprints(root: Path, *study_scripts: str) -> dict[str, str]:
    """Hash all package Python sources and the study's scripts and hash helper.

    Include the whole package so new algorithms and shared measurement helpers
    are covered without maintaining a separate list in each study. Script paths
    are repository-relative; output keeps the existing POSIX path-to-SHA schema.
    """
    paths = {path.relative_to(root).as_posix() for path in (root / "search_algos").rglob("*.py")}
    paths.update(("scripts/study_sources.py", *study_scripts))
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in sorted(paths)}
