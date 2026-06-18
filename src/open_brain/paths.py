"""Profile-aware filesystem paths."""

from __future__ import annotations

import os
from pathlib import Path


def brain_home() -> Path:
    """Return the local Open Brain home directory."""

    raw = os.getenv("BRAIN_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".open-brain"


def default_db_path() -> Path:
    """Return the default SQLite database path."""

    raw = os.getenv("BRAIN_DB")
    if raw:
        return Path(raw).expanduser()
    return brain_home() / "brain.db"


def ensure_parent(path: Path) -> None:
    """Create the parent directory for *path* if needed."""

    path.expanduser().parent.mkdir(parents=True, exist_ok=True)

