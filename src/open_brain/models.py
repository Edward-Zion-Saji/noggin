"""Typed data exchanged between adapters and the brain core."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from .errors import EmptyContentError, InvalidEnvelopeError, PayloadTooLargeError
from .observability import utc_now

MAX_CONTENT_CHARS = 250_000


def stable_json(data: dict[str, Any]) -> str:
    """Return deterministic compact JSON."""

    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def content_hash(content: str) -> str:
    """Return a stable SHA-256 hash for content."""

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    """Return a prefixed random id."""

    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class SourceEvent:
    """Normalized event produced by any surface or agent."""

    content: str
    source: str = "cli"
    kind: str = "note"
    workspace: str = "default"
    actor: str = "unknown"
    source_id: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def validate(self) -> "SourceEvent":
        """Return self when valid, otherwise raise a named error."""

        if not isinstance(self.content, str):
            raise InvalidEnvelopeError("content must be a string")
        normalized = self.content.strip()
        if not normalized:
            raise EmptyContentError("content is empty")
        if len(normalized) > MAX_CONTENT_CHARS:
            raise PayloadTooLargeError(
                f"content length {len(normalized)} exceeds {MAX_CONTENT_CHARS}"
            )
        if not self.source.strip():
            raise InvalidEnvelopeError("source is required")
        if not self.kind.strip():
            raise InvalidEnvelopeError("kind is required")
        if not self.workspace.strip():
            raise InvalidEnvelopeError("workspace is required")
        return self

    def normalized_content(self) -> str:
        """Return whitespace-trimmed content."""

        return self.content.strip()

    def effective_idempotency_key(self, redacted_content: str) -> str:
        """Return caller key or a stable key derived from event provenance."""

        if self.idempotency_key:
            return self.idempotency_key
        if self.source_id:
            return f"{self.workspace}:{self.source}:{self.source_id}"
        digest = content_hash(
            stable_json(
                {
                    "workspace": self.workspace,
                    "source": self.source,
                    "actor": self.actor,
                    "kind": self.kind,
                    "content_hash": content_hash(redacted_content),
                }
            )
        )
        return f"{self.workspace}:{self.source}:{digest}"


@dataclass(frozen=True)
class Observation:
    """A durable extracted fact or workflow lesson."""

    content: str
    event_id: str
    kind: str = "note"
    subject: str = "general"
    predicate: str = "mentions"
    object: str = ""
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("obs"))
    created_at: str = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-ready observation data."""

        return {
            "id": self.id,
            "event_id": self.event_id,
            "kind": self.kind,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "content": self.content,
            "confidence": self.confidence,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

