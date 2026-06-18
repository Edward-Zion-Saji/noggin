"""Local-first snapshot sync and token-protected peer server."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .brain import BrainService
from .errors import SyncAuthError
from .observability import log_event, utc_now
from .store import BrainStore


def export_snapshot(store: BrainStore) -> dict[str, Any]:
    """Return a portable snapshot of append-only brain state."""

    conn = store.conn
    return {
        "format": "open-brain-snapshot-v1",
        "exported_at": utc_now(),
        "events": [dict(row) for row in conn.execute("SELECT * FROM events").fetchall()],
        "observations": [dict(row) for row in conn.execute("SELECT * FROM observations").fetchall()],
        "entities": [dict(row) for row in conn.execute("SELECT * FROM entities").fetchall()],
        "edges": [dict(row) for row in conn.execute("SELECT * FROM edges").fetchall()],
        "skill_proposals": [
            dict(row) for row in conn.execute("SELECT * FROM skill_proposals").fetchall()
        ],
    }


def import_snapshot(store: BrainStore, snapshot: dict[str, Any]) -> dict[str, int]:
    """Import a snapshot idempotently."""

    if snapshot.get("format") != "open-brain-snapshot-v1":
        raise ValueError("unsupported snapshot format")
    counts = {"events": 0, "observations": 0, "entities": 0, "edges": 0, "skill_proposals": 0}
    conn = store.conn
    try:
        for row in snapshot.get("events", []):
            if conn.execute("SELECT 1 FROM events WHERE id = ?", (row["id"],)).fetchone():
                continue
            conn.execute(
                """
                INSERT INTO events (
                  id, source, source_id, workspace, actor, kind, content, content_hash,
                  idempotency_key, metadata_json, redaction_json, extraction_status,
                  extraction_error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["source"],
                    row.get("source_id"),
                    row["workspace"],
                    row["actor"],
                    row["kind"],
                    row["content"],
                    row["content_hash"],
                    row["idempotency_key"],
                    row["metadata_json"],
                    row["redaction_json"],
                    row["extraction_status"],
                    row.get("extraction_error"),
                    row["created_at"],
                ),
            )
            conn.execute(
                "INSERT INTO events_fts(event_id, content, source, actor, kind) VALUES (?, ?, ?, ?, ?)",
                (row["id"], row["content"], row["source"], row["actor"], row["kind"]),
            )
            counts["events"] += 1

        for row in snapshot.get("observations", []):
            if conn.execute("SELECT 1 FROM observations WHERE id = ?", (row["id"],)).fetchone():
                continue
            conn.execute(
                """
                INSERT INTO observations (
                  id, event_id, kind, subject, predicate, object, content, confidence,
                  tags_json, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["event_id"],
                    row["kind"],
                    row["subject"],
                    row["predicate"],
                    row["object"],
                    row["content"],
                    row["confidence"],
                    row["tags_json"],
                    row["metadata_json"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
            conn.execute(
                """
                INSERT INTO observations_fts(observation_id, content, subject, object, kind)
                VALUES (?, ?, ?, ?, ?)
                """,
                (row["id"], row["content"], row["subject"], row["object"], row["kind"]),
            )
            counts["observations"] += 1

        for table in ("entities", "edges", "skill_proposals"):
            for row in snapshot.get(table, []):
                if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row["id"],)).fetchone():
                    continue
                columns = list(row.keys())
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT INTO {table}({', '.join(columns)}) VALUES ({placeholders})",
                    [row[column] for column in columns],
                )
                counts[table] += 1
        conn.commit()
        log_event("brain.sync.imported", **counts)
        return counts
    except Exception:
        conn.rollback()
        raise


def cmd_sync_export(args: argparse.Namespace) -> int:
    brain = BrainService(db_path=args.db)
    snapshot = export_snapshot(brain.store)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "events": len(snapshot["events"])}))
    return 0


def cmd_sync_import(args: argparse.Namespace) -> int:
    brain = BrainService(db_path=args.db)
    snapshot = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
    counts = import_snapshot(brain.store, snapshot)
    print(json.dumps({"ok": True, "imported": counts}, indent=2, sort_keys=True))
    return 0


def cmd_sync_serve(args: argparse.Namespace) -> int:
    token = args.token or os.getenv("BRAIN_SYNC_TOKEN", "")
    if not token:
        raise SyncAuthError("BRAIN_SYNC_TOKEN or --token is required for sync serve")
    server = ThreadingHTTPServer((args.host, args.port), _handler(args.db, token))
    print(f"Brain sync peer listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def cmd_sync_push(args: argparse.Namespace) -> int:
    brain = BrainService(db_path=args.db)
    snapshot = export_snapshot(brain.store)
    result = _request_json(
        args.url.rstrip("/") + "/sync/import",
        token=args.token or os.getenv("BRAIN_SYNC_TOKEN", ""),
        body=snapshot,
    )
    print(json.dumps({"ok": True, "peer": result}, indent=2, sort_keys=True))
    return 0


def cmd_sync_pull(args: argparse.Namespace) -> int:
    brain = BrainService(db_path=args.db)
    snapshot = _request_json(
        args.url.rstrip("/") + "/sync/export",
        token=args.token or os.getenv("BRAIN_SYNC_TOKEN", ""),
    )
    counts = import_snapshot(brain.store, snapshot)
    print(json.dumps({"ok": True, "imported": counts}, indent=2, sort_keys=True))
    return 0


def _handler(db_path: str, token: str) -> type[BaseHTTPRequestHandler]:
    class SyncHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._json({"ok": True, "adapter": "sync"})
                return
            if self.path == "/sync/export":
                if not self._authorized():
                    return
                brain = BrainService(db_path=db_path)
                self._json(export_snapshot(brain.store))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/sync/import":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not self._authorized():
                return
            brain = BrainService(db_path=db_path)
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            snapshot = json.loads(raw.decode("utf-8"))
            counts = import_snapshot(brain.store, snapshot)
            self._json({"ok": True, "imported": counts})

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            if header != f"Bearer {token}":
                self._json({"ok": False, "error": "unauthorized"}, status=401)
                return False
            return True

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: Any) -> None:
            log_event("brain.sync.http", message=format % args)

    return SyncHandler


def _request_json(url: str, *, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if not token:
        raise SyncAuthError("BRAIN_SYNC_TOKEN or --token is required")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if body is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "open-brain-plugin/0.1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SyncAuthError(f"sync peer HTTP {exc.code}: {exc.read().decode('utf-8')[:300]}") from exc
