# Load repo-root .env into os.environ for local CLI runs.
# Non-empty shell values win; empty/missing values are filled from .env.

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_file_candidates() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)

    add(repo_root() / ".env")
    for parent in [Path.cwd(), *Path.cwd().parents]:
        add(parent / ".env")
        if (parent / ".git").is_dir():
            break
    return out


def _parse_env_line(raw: str) -> tuple[str, str] | None:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, _, value = line.partition("=")
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return key, value


def load_repo_env() -> None:
    """Load KEY=VALUE pairs from the first repo .env file found."""
    for path in _env_file_candidates():
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(raw)
            if parsed is None:
                continue
            key, value = parsed
            if os.environ.get(key):
                continue
            os.environ[key] = value
        return
