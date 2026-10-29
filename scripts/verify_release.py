"""Build and smoke-test the wheel in a clean environment outside this checkout.

Run with ``python scripts/verify_release.py``. Only pip and the standard library
are needed; pip installs the build dependencies declared in pyproject.toml.
Source staging, build output, the virtual environment, and reports are temporary.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _environment() -> dict[str, str]:
    """Keep checkout imports and inherited coverage hooks out of the smoke run."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "COVERAGE_"))
    }
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _run(arguments: list[str], directory: Path, environment: dict[str, str]) -> None:
    subprocess.run(arguments, cwd=directory, env=environment, check=True, timeout=180)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    environment = _environment()
    with tempfile.TemporaryDirectory(prefix="search-algos-release-") as directory:
        temporary = Path(directory).resolve()
        if temporary.is_relative_to(root):
            raise RuntimeError("The system temporary directory must be outside the checkout")
        source = temporary / "source"
        shutil.copytree(
            root,
            source,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "venv",
                "build",
                "dist",
                "*.egg-info",
                "__pycache__",
                ".mypy_cache",
                ".ruff_cache",
                ".pytest_cache",
                ".coverage*",
                "coverage.xml",
                "htmlcov",
                "benchmark-smoke.*",
            ),
        )
        work = temporary / "work"
        work.mkdir()
        wheels = temporary / "wheels"
        print("Building a wheel from a temporary source copy...", flush=True)
        _run(
            [
                sys.executable,
                "-I",
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(wheels),
                str(source),
            ],
            work,
            environment,
        )
        built = list(wheels.glob("*.whl"))
        if len(built) != 1:
            raise RuntimeError(f"Expected exactly one project wheel, found {len(built)}")
        isolated = temporary / "venv"
        venv.EnvBuilder(with_pip=True).create(isolated)
        python = isolated / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        _run(
            [str(python), "-I", "-m", "pip", "install", "--no-deps", "--no-index", str(built[0])],
            work,
            environment,
        )
        smoke = work / "installed_smoke.py"
        shutil.copy2(source / "tests" / "installed_smoke.py", smoke)
        print("Checking the installed wheel from outside the checkout...", flush=True)
        _run([str(python), "-I", str(smoke), "-v"], work, environment)
    print("Installed-wheel verification passed; temporary files removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
