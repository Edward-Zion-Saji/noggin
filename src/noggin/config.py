"""User configuration file loading for local installs."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from .paths import brain_home

_ENV_KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def user_env_path() -> Path:
    """Return the Noggin env-file path."""

    raw = os.getenv("NOGGIN_ENV")
    if raw:
        return Path(raw).expanduser()
    return brain_home() / "noggin.env"


def load_user_env(path: str | Path | None = None) -> bool:
    """Load KEY=value config from the user env file without overriding process env."""

    env_path = Path(path).expanduser() if path else user_env_path()
    if not env_path.exists():
        return False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if separator != "=" or not _ENV_KEY.fullmatch(key) or key in os.environ:
            continue
        os.environ[key] = _parse_env_value(value.strip())
    return True


def _parse_env_value(value: str) -> str:
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        try:
            parsed = shlex.split(value, posix=True)
        except ValueError:
            return value.strip("\"'")
        return parsed[0] if parsed else ""
    return value
