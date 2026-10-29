"""Best-effort environment and source provenance for benchmark reports."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _project_version(root: Path) -> str | None:
    """Read this project's static version without a Python 3.11 TOML dependency."""
    try:
        document = (root / "pyproject.toml").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    project = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", document)
    if project is None:
        return None
    if not re.search(r"(?m)^name\s*=\s*['\"]search-algos['\"]\s*$", project[1]):
        return None
    version = re.search(r"(?m)^version\s*=\s*['\"]([^'\"]+)['\"]\s*$", project[1])
    return version[1] if version else None


def _source_root() -> Path | None:
    """Only identify a checkout adjacent to this module, never the caller's cwd."""
    root = Path(__file__).resolve().parents[1]
    return root if _project_version(root) is not None else None


def _command(arguments: list[str], cwd: Path | None = None) -> str | None:
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            arguments,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _git_metadata(root: Path | None) -> tuple[str | None, bool | None]:
    if root is None or not (root / ".git").exists():
        return None, None
    top_level = _command(["git", "rev-parse", "--show-toplevel"], root)
    if top_level is None or Path(top_level).resolve() != root.resolve():
        return None, None
    commit = _command(["git", "rev-parse", "HEAD"], root)
    if commit is None or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) is None:
        return None, None
    status = _command(["git", "status", "--porcelain", "--untracked-files=normal"], root)
    return commit, bool(status) if status is not None else None


def _package_version(root: Path | None) -> str | None:
    if root is not None:
        source_version = _project_version(root)
        if source_version is not None:
            return source_version
    try:
        return importlib.metadata.version("search-algos")
    except importlib.metadata.PackageNotFoundError:
        return None


def _cpu_model() -> str | None:
    """Read a CPU model name without identifiers such as serial numbers."""
    try:
        if sys.platform == "win32":
            winreg = importlib.import_module("winreg")
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if isinstance(value, str) and value.strip():
                return value.strip()
        elif sys.platform.startswith("linux"):
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition(":")
                if key.strip() in ("model name", "Hardware") and value.strip():
                    return value.strip()
        elif sys.platform == "darwin":
            value = _command(["sysctl", "-n", "machdep.cpu.brand_string"])
            if value:
                return value
    except (OSError, ImportError, UnicodeError):
        pass
    return platform.processor().strip() or None


def collect_metadata() -> dict[str, Any]:
    """Collect portable metadata; unavailable source and hardware fields are null."""
    root = _source_root()
    commit, dirty = _git_metadata(root)
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count() or 1,
        "timer": "perf_counter_ns",
        "multiprocessing_start_method": "spawn",
        "cpu_model": _cpu_model(),
        "git_commit": commit,
        "git_dirty": dirty,
        "package_version": _package_version(root),
    }
