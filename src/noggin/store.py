"""SQLite storage for the local-first brain."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .errors import StoreReadError, StoreWriteError
from .models import Observation, SourceEvent, new_id, stable_json
from .observability import log_event, utc_now
from .paths import ensure_parent


class BrainStore:
    """SQLite-backed event log, observations, graph, and proposals."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        ensure_parent(self.db_path)
        self.conn = sqlite3.connect(str(self.db_path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.initialize()

    def initialize(self) -> None:
        """Create all schema objects if missing."""

        try:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                  id TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  source_id TEXT,
                  workspace TEXT NOT NULL,
                  actor TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  content TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  metadata_json TEXT NOT NULL,
                  redaction_json TEXT NOT NULL,
                  extraction_status TEXT NOT NULL DEFAULT 'pending',
                  extraction_error TEXT,
                  created_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                  event_id UNINDEXED,
                  content,
                  source,
                  actor,
                  kind
                );

                CREATE TABLE IF NOT EXISTS observations (
                  id TEXT PRIMARY KEY,
                  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                  kind TEXT NOT NULL,
                  subject TEXT NOT NULL,
                  predicate TEXT NOT NULL,
                  object TEXT NOT NULL,
                  content TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  tags_json TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
                  observation_id UNINDEXED,
                  content,
                  subject,
                  object,
                  kind
                );

                CREATE TABLE IF NOT EXISTS entities (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL UNIQUE,
                  type TEXT NOT NULL DEFAULT 'unknown',
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS edges (
                  id TEXT PRIMARY KEY,
                  from_entity TEXT NOT NULL,
                  to_entity TEXT NOT NULL,
                  relation TEXT NOT NULL,
                  evidence_event_id TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skill_proposals (
                  id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  target_path TEXT NOT NULL,
                  patch TEXT NOT NULL,
                  new_content TEXT NOT NULL,
                  status TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            self.conn.commit()
        except sqlite3.DatabaseError as exc:
            raise StoreWriteError(f"failed to initialize store: {exc}") from exc

    def append_event(
        self,
        event: SourceEvent,
        *,
        redacted_content: str,
        redaction_findings: list[str],
        content_hash: str,
        idempotency_key: str,
    ) -> tuple[str, bool]:
        """Append a source event. Return `(event_id, duplicate)`."""

        existing = self.conn.execute(
            "SELECT id FROM events WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing:
            return str(existing["id"]), True

        event_id = new_id("evt")
        try:
            self.conn.execute(
                """
                INSERT INTO events (
                  id, source, source_id, workspace, actor, kind, content, content_hash,
                  idempotency_key, metadata_json, redaction_json, extraction_status,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    event_id,
                    event.source,
                    event.source_id,
                    event.workspace,
                    event.actor,
                    event.kind,
                    redacted_content,
                    content_hash,
                    idempotency_key,
                    stable_json(event.metadata),
                    stable_json({"findings": redaction_findings}),
                    event.created_at,
                ),
            )
            self.conn.execute(
                "INSERT INTO events_fts(event_id, content, source, actor, kind) VALUES (?, ?, ?, ?, ?)",
                (event_id, redacted_content, event.source, event.actor, event.kind),
            )
            self.conn.commit()
            log_event("brain.event.appended", event_id=event_id, source=event.source, kind=event.kind)
            return event_id, False
        except sqlite3.DatabaseError as exc:
            self.conn.rollback()
            raise StoreWriteError(f"failed to append event: {exc}") from exc

    def set_event_extraction(self, event_id: str, status: str, error: str | None = None) -> None:
        """Update extraction status for an event."""

        try:
            self.conn.execute(
                "UPDATE events SET extraction_status = ?, extraction_error = ? WHERE id = ?",
                (status, error, event_id),
            )
            self.conn.commit()
        except sqlite3.DatabaseError as exc:
            self.conn.rollback()
            raise StoreWriteError(f"failed to update extraction status: {exc}") from exc

    def add_observations(self, observations: list[Observation]) -> None:
        """Persist extracted observations."""

        if not observations:
            return
        try:
            for obs in observations:
                self.conn.execute(
                    """
                    INSERT INTO observations (
                      id, event_id, kind, subject, predicate, object, content,
                      confidence, tags_json, metadata_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obs.id,
                        obs.event_id,
                        obs.kind,
                        obs.subject,
                        obs.predicate,
                        obs.object,
                        obs.content,
                        obs.confidence,
                        stable_json({"tags": obs.tags}),
                        stable_json(obs.metadata),
                        obs.created_at,
                        obs.created_at,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT INTO observations_fts(observation_id, content, subject, object, kind)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (obs.id, obs.content, obs.subject, obs.object, obs.kind),
                )
                self._upsert_entity(obs.subject)
                if obs.object:
                    self._upsert_entity(obs.object)
                    self.conn.execute(
                        """
                        INSERT INTO edges (
                          id, from_entity, to_entity, relation, evidence_event_id,
                          confidence, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_id("edge"),
                            obs.subject,
                            obs.object,
                            obs.predicate,
                            obs.event_id,
                            obs.confidence,
                            utc_now(),
                        ),
                    )
            self.conn.commit()
            log_event("brain.observations.added", count=len(observations))
        except sqlite3.DatabaseError as exc:
            self.conn.rollback()
            raise StoreWriteError(f"failed to add observations: {exc}") from exc

    def _upsert_entity(self, name: str, entity_type: str = "unknown") -> None:
        cleaned = name.strip() or "general"
        self.conn.execute(
            "INSERT OR IGNORE INTO entities(id, name, type, created_at) VALUES (?, ?, ?, ?)",
            (new_id("ent"), cleaned, entity_type, utc_now()),
        )

    def list_entities(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return graph entities."""

        try:
            rows = self.conn.execute(
                "SELECT * FROM entities ORDER BY name COLLATE NOCASE LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.DatabaseError as exc:
            raise StoreReadError(f"failed to list graph entities: {exc}") from exc

    def entity_graph(self, name: str, *, limit: int = 100) -> dict[str, Any] | None:
        """Return one entity with related observations and edges."""

        try:
            entity = self.conn.execute("SELECT * FROM entities WHERE name = ?", (name,)).fetchone()
            if not entity:
                return None
            outgoing = self.conn.execute(
                """
                SELECT * FROM edges
                WHERE from_entity = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (name, limit),
            ).fetchall()
            incoming = self.conn.execute(
                """
                SELECT * FROM edges
                WHERE to_entity = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (name, limit),
            ).fetchall()
            observations = self.conn.execute(
                """
                SELECT
                  o.*, e.source, e.actor, e.workspace, e.created_at AS event_created_at
                FROM observations o
                JOIN events e ON e.id = o.event_id
                WHERE o.subject = ? OR o.object = ?
                ORDER BY o.created_at DESC
                LIMIT ?
                """,
                (name, name, limit),
            ).fetchall()
            return {
                "entity": dict(entity),
                "outgoing": [dict(row) for row in outgoing],
                "incoming": [dict(row) for row in incoming],
                "observations": [_graph_observation_row_to_dict(row) for row in observations],
            }
        except sqlite3.DatabaseError as exc:
            raise StoreReadError(f"failed to load graph entity {name}: {exc}") from exc

    def recall(self, query: str, *, limit: int = 10, workspace: str | None = None) -> list[dict[str, Any]]:
        """Search observations first, then events."""

        terms = _fts_terms(query)
        if not terms:
            return []
        params: list[Any] = [terms]
        workspace_filter = ""
        if workspace:
            workspace_filter = "AND e.workspace = ?"
            params.append(workspace)
        params.append(limit)
        try:
            rows = self.conn.execute(
                f"""
                SELECT
                  o.id AS observation_id, o.kind, o.subject, o.predicate, o.object,
                  o.content, o.confidence, o.tags_json, o.metadata_json, o.created_at,
                  e.id AS event_id, e.source, e.actor, e.workspace, e.created_at AS event_created_at,
                  bm25(observations_fts) AS rank
                FROM observations_fts
                JOIN observations o ON o.id = observations_fts.observation_id
                JOIN events e ON e.id = o.event_id
                WHERE observations_fts MATCH ? {workspace_filter}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            ).fetchall()
            if rows:
                return [_row_to_dict(row) for row in rows]

            params = [terms]
            if workspace:
                params.append(workspace)
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT
                  NULL AS observation_id, e.kind, 'event' AS subject, 'mentions' AS predicate,
                  '' AS object, e.content, 0.3 AS confidence, '{{"tags":[]}}' AS tags_json,
                  e.metadata_json, e.created_at,
                  e.id AS event_id, e.source, e.actor, e.workspace, e.created_at AS event_created_at,
                  bm25(events_fts) AS rank
                FROM events_fts
                JOIN events e ON e.id = events_fts.event_id
                WHERE events_fts MATCH ? {workspace_filter}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [_row_to_dict(row) for row in rows]
        except sqlite3.DatabaseError as exc:
            raise StoreReadError(f"failed to recall query: {exc}") from exc

    def recent_events(self, *, limit: int = 25) -> list[dict[str, Any]]:
        """Return recent events."""

        rows = self.conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_event_row_to_dict(row) for row in rows]

    def list_observations(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent observations."""

        rows = self.conn.execute(
            "SELECT * FROM observations ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_observation_row_to_dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        """Return high-level store stats."""

        try:
            return {
                "db_path": str(self.db_path),
                "events": self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "observations": self.conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
                "entities": self.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                "skill_proposals": self.conn.execute(
                    "SELECT COUNT(*) FROM skill_proposals"
                ).fetchone()[0],
            }
        except sqlite3.DatabaseError as exc:
            raise StoreReadError(f"failed to load stats: {exc}") from exc

    def create_skill_proposal(
        self,
        *,
        title: str,
        reason: str,
        target_path: str,
        patch: str,
        new_content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a skill proposal and return its id."""

        proposal_id = new_id("skill")
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO skill_proposals (
              id, title, reason, target_path, patch, new_content, status,
              metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (
                proposal_id,
                title,
                reason,
                target_path,
                patch,
                new_content,
                stable_json(metadata or {}),
                now,
                now,
            ),
        )
        self.conn.commit()
        log_event("brain.skill_proposal.created", proposal_id=proposal_id, target_path=target_path)
        return proposal_id

    def get_skill_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """Return one skill proposal or None."""

        row = self.conn.execute(
            "SELECT * FROM skill_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if not row:
            return None
        return _proposal_row_to_dict(row)

    def list_skill_proposals(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent skill proposals."""

        if status:
            rows = self.conn.execute(
                "SELECT * FROM skill_proposals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM skill_proposals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_proposal_row_to_dict(row) for row in rows]

    def set_skill_proposal_status(self, proposal_id: str, status: str, metadata: dict[str, Any] | None = None) -> None:
        """Set skill proposal status and merge metadata."""

        proposal = self.get_skill_proposal(proposal_id)
        if not proposal:
            return
        merged = proposal.get("metadata", {})
        if metadata:
            merged.update(metadata)
        self.conn.execute(
            """
            UPDATE skill_proposals
            SET status = ?, metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, stable_json(merged), utc_now(), proposal_id),
        )
        self.conn.commit()
        log_event("brain.skill_proposal.status", proposal_id=proposal_id, status=status)


def _fts_terms(query: str) -> str:
    words = [part for part in "".join(ch if ch.isalnum() else " " for ch in query).split() if part]
    return " OR ".join(words[:12])


def _safe_load_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["tags"] = _safe_load_json(data.pop("tags_json", "{}")).get("tags", [])
    data["metadata"] = _safe_load_json(data.pop("metadata_json", "{}"))
    return data


def _event_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = _safe_load_json(data.pop("metadata_json", "{}"))
    data["redaction"] = _safe_load_json(data.pop("redaction_json", "{}"))
    return data


def _observation_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["tags"] = _safe_load_json(data.pop("tags_json", "{}")).get("tags", [])
    data["metadata"] = _safe_load_json(data.pop("metadata_json", "{}"))
    return data


def _graph_observation_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = _observation_row_to_dict(row)
    return data


def _proposal_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = _safe_load_json(data.pop("metadata_json", "{}"))
    return data
