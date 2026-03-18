from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _compose_files(mode: str) -> list[str]:
    base = ["-f", "docker-compose.yml"]
    if mode == "dev":
        return [*base, "-f", "docker-compose.dev.yml"]
    return base


def _run(command: list[str], cwd: Path) -> int:
    return subprocess.run(command, cwd=cwd, check=False).returncode


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    if len(sys.argv) < 2:
        print("Usage: python scripts/docker.py [prod|dev|down|ps|logs]")
        return 1

    action = sys.argv[1].lower()

    if action in {"prod", "dev"}:
        command = [
            "docker",
            "compose",
            *_compose_files(action),
            "up",
            "-d",
            "--build",
        ]
        return _run(command, repo_root)

    if action == "down":
        command = ["docker", "compose", "-f", "docker-compose.yml", "down", *sys.argv[2:]]
        return _run(command, repo_root)

    if action == "ps":
        command = ["docker", "compose", "-f", "docker-compose.yml", "ps", *sys.argv[2:]]
        return _run(command, repo_root)

    if action == "logs":
        command = ["docker", "compose", "-f", "docker-compose.yml", "logs", *sys.argv[2:]]
        return _run(command, repo_root)

    print(f"Unsupported action: {action}")
    print("Usage: python scripts/docker.py [prod|dev|down|ps|logs]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
