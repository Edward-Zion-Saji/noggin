"""Structured logging helpers."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import brain_home


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def configure_logging() -> None:
    """Configure default file logging once."""

    if logging.getLogger("noggin").handlers:
        return
    log_dir = Path(
        os.getenv("NOGGIN_LOG_DIR") or os.getenv("BRAIN_LOG_DIR", str(brain_home() / "logs"))
    ).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / "brain.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("noggin")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def log_event(event_type: str, **fields: Any) -> None:
    """Write one structured log event."""

    configure_logging()
    payload = {"ts": utc_now(), "event": event_type, **fields}
    logging.getLogger("noggin").info(json.dumps(payload, sort_keys=True))
