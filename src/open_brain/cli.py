"""Command-line interface for Open Brain Plugin."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .brain import BrainService
from .errors import BrainError
from .paths import default_db_path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except BrainError as exc:
        print(json.dumps({"ok": False, "error": exc.__class__.__name__, "message": str(exc)}))
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain", description="Local-first brain for agents and teams.")
    parser.add_argument("--db", default=str(default_db_path()), help="SQLite brain database path.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Show runtime status.")
    doctor.set_defaults(func=cmd_doctor)

    ingest = sub.add_parser("ingest", help="Ingest text into the brain.")
    ingest.add_argument("content", nargs="*", help="Text to ingest. Reads stdin when omitted.")
    ingest.add_argument("--source", default="cli")
    ingest.add_argument("--kind", default="note")
    ingest.add_argument("--workspace", default="default")
    ingest.add_argument("--actor", default="unknown")
    ingest.add_argument("--source-id")
    ingest.add_argument("--idempotency-key")
    ingest.add_argument("--metadata-json", default="{}")
    ingest.set_defaults(func=cmd_ingest)

    recall = sub.add_parser("recall", help="Recall brain context.")
    recall.add_argument("query", nargs="+")
    recall.add_argument("--limit", type=int, default=10)
    recall.add_argument("--workspace")
    recall.set_defaults(func=cmd_recall)

    reflect = sub.add_parser("reflect", help="Synthesize matching brain context.")
    reflect.add_argument("query", nargs="+")
    reflect.add_argument("--limit", type=int, default=8)
    reflect.add_argument("--workspace")
    reflect.set_defaults(func=cmd_reflect)

    stats = sub.add_parser("stats", help="Show brain stats.")
    stats.set_defaults(func=cmd_stats)
    return parser


def service(args: argparse.Namespace) -> BrainService:
    return BrainService(db_path=args.db)


def cmd_doctor(args: argparse.Namespace) -> int:
    brain = service(args)
    payload = {
        "ok": True,
        "db": str(brain.store.db_path),
        "stats": brain.stats(),
    }
    print_json(payload)
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    content = " ".join(args.content).strip()
    if not content:
        content = sys.stdin.read()
    metadata = _json_arg(args.metadata_json)
    brain = service(args)
    result = brain.ingest(
        content,
        source=args.source,
        kind=args.kind,
        workspace=args.workspace,
        actor=args.actor,
        source_id=args.source_id,
        idempotency_key=args.idempotency_key,
        metadata=metadata,
    )
    print_json({"ok": True, **result})
    return 0


def cmd_recall(args: argparse.Namespace) -> int:
    brain = service(args)
    results = brain.recall(" ".join(args.query), limit=args.limit, workspace=args.workspace)
    print_json({"ok": True, "results": results})
    return 0


def cmd_reflect(args: argparse.Namespace) -> int:
    brain = service(args)
    result = brain.reflect(" ".join(args.query), limit=args.limit, workspace=args.workspace)
    print_json({"ok": True, **result})
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    print_json({"ok": True, "stats": service(args).stats()})
    return 0


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _json_arg(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("--metadata-json must be a JSON object")
    return data


if __name__ == "__main__":
    raise SystemExit(main())

