from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_step(command: list[str], cwd: Path) -> int:
    return subprocess.run(command, cwd=cwd, check=False).returncode


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    python = sys.executable

    steps = [
        [python, "-m", "ruff", "check", "src", "tests"],
        [python, "-m", "mypy", "src", "tests"],
        [python, "-m", "pytest", "tests", "-q"],
    ]
    for step in steps:
        code = run_step(step, repo_root)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
