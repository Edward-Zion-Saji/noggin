"""High-level brain service used by CLI and adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import LlmExtractionError
from .models import SourceEvent, content_hash
from .observability import log_event
from .paths import default_db_path
from .redaction import redact_secrets
from .skills import apply_skill_proposal, propose_skill, reject_skill_proposal
from .store import BrainStore
from .workers import NogginWorkers


class BrainService:
    """Facade around validation, redaction, extraction, recall, and storage."""

    def __init__(self, db_path: str | Path | None = None, workers: NogginWorkers | None = None):
        self.store = BrainStore(db_path or default_db_path())
        self.workers = workers or NogginWorkers()

    def ingest(
        self,
        content: str,
        *,
        source: str = "cli",
        kind: str = "note",
        workspace: str = "default",
        actor: str = "unknown",
        source_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        strict_secrets: bool = False,
    ) -> dict[str, Any]:
        """Validate and ingest content into the brain."""

        event = SourceEvent(
            content=content,
            source=source,
            kind=kind,
            workspace=workspace,
            actor=actor,
            source_id=source_id,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
        ).validate()
        redaction = redact_secrets(event.normalized_content(), strict=strict_secrets)
        event_hash = content_hash(redaction.content)
        key = event.effective_idempotency_key(redaction.content)
        event_id, duplicate = self.store.append_event(
            event,
            redacted_content=redaction.content,
            redaction_findings=redaction.findings,
            content_hash=event_hash,
            idempotency_key=key,
        )
        if duplicate:
            log_event("brain.event.duplicate", event_id=event_id, source=source)
            return {
                "event_id": event_id,
                "duplicate": True,
                "observations_added": 0,
                "extraction_status": "skipped_duplicate",
                "redactions": redaction.findings,
            }

        try:
            observations = self.workers.arrange_event(event, event_id, redaction.content)
            self.store.add_observations(observations)
            self.store.set_event_extraction(event_id, "ok")
            return {
                "event_id": event_id,
                "duplicate": False,
                "observations_added": len(observations),
                "extraction_status": "ok",
                "redactions": redaction.findings,
            }
        except LlmExtractionError as exc:
            self.store.set_event_extraction(event_id, "failed", str(exc))
            log_event("brain.extraction.failed", event_id=event_id, error=str(exc))
            return {
                "event_id": event_id,
                "duplicate": False,
                "observations_added": 0,
                "extraction_status": "failed",
                "extraction_error": str(exc),
                "redactions": redaction.findings,
            }

    def recall(self, query: str, *, limit: int = 10, workspace: str | None = None) -> list[dict[str, Any]]:
        """Recall relevant observations with provenance."""

        return self.store.recall(query, limit=limit, workspace=workspace)

    def reflect(self, query: str, *, limit: int = 8, workspace: str | None = None) -> dict[str, Any]:
        """Return a compact synthesis over recall results."""

        results = self.recall(query, limit=limit, workspace=workspace)
        if not results:
            return {"query": query, "summary": "No matching brain context found.", "results": []}
        summary = self.workers.reflect(query, results[:limit])
        return {
            "query": query,
            "summary": summary,
            "results": results,
        }

    def stats(self) -> dict[str, Any]:
        """Return store stats."""

        return self.store.stats()

    def propose_skill(
        self,
        content: str,
        *,
        title: str | None = None,
        target_path: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Create a guarded skill proposal."""

        draft = self.workers.draft_skill(
            content=content,
            title=title,
            target_path=target_path,
            reason=reason,
        )
        return propose_skill(self.store, draft=draft)

    def apply_skill(
        self,
        proposal_id: str,
        *,
        allow_root: str | Path,
        run_tests: str | None = None,
    ) -> dict[str, Any]:
        """Apply a skill proposal through the safety gate."""

        return apply_skill_proposal(
            self.store,
            proposal_id,
            allow_root=allow_root,
            run_tests=run_tests,
        )

    def reject_skill(self, proposal_id: str, *, reason: str = "") -> dict[str, Any]:
        """Reject a skill proposal."""

        return reject_skill_proposal(self.store, proposal_id, reason=reason)

    def list_skill_proposals(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List skill proposals."""

        return self.store.list_skill_proposals(status=status, limit=limit)
