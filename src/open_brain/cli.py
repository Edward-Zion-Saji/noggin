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

    skills = sub.add_parser("skills", help="Skill proposal workflow.")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills_propose = skills_sub.add_parser("propose", help="Create a skill proposal.")
    skills_propose.add_argument("--content", help="Lesson content. Reads stdin when omitted.")
    skills_propose.add_argument("--title")
    skills_propose.add_argument("--target-path")
    skills_propose.add_argument("--reason")
    skills_propose.set_defaults(func=cmd_skills_propose)

    skills_list = skills_sub.add_parser("list", help="List skill proposals.")
    skills_list.add_argument("--status")
    skills_list.add_argument("--limit", type=int, default=50)
    skills_list.set_defaults(func=cmd_skills_list)

    skills_show = skills_sub.add_parser("show", help="Show one skill proposal.")
    skills_show.add_argument("proposal_id")
    skills_show.set_defaults(func=cmd_skills_show)

    skills_apply = skills_sub.add_parser("apply", help="Apply one skill proposal.")
    skills_apply.add_argument("proposal_id")
    skills_apply.add_argument("--allow-root", required=True)
    skills_apply.add_argument("--run-tests")
    skills_apply.set_defaults(func=cmd_skills_apply)

    skills_reject = skills_sub.add_parser("reject", help="Reject one skill proposal.")
    skills_reject.add_argument("proposal_id")
    skills_reject.add_argument("--reason", default="")
    skills_reject.set_defaults(func=cmd_skills_reject)
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


def cmd_skills_propose(args: argparse.Namespace) -> int:
    content = args.content or sys.stdin.read()
    proposal = service(args).propose_skill(
        content,
        title=args.title,
        target_path=args.target_path,
        reason=args.reason,
    )
    print_json({"ok": True, "proposal": proposal})
    return 0


def cmd_skills_list(args: argparse.Namespace) -> int:
    proposals = service(args).list_skill_proposals(status=args.status, limit=args.limit)
    print_json({"ok": True, "proposals": proposals})
    return 0


def cmd_skills_show(args: argparse.Namespace) -> int:
    proposal = service(args).store.get_skill_proposal(args.proposal_id)
    print_json({"ok": bool(proposal), "proposal": proposal})
    return 0 if proposal else 1


def cmd_skills_apply(args: argparse.Namespace) -> int:
    proposal = service(args).apply_skill(
        args.proposal_id,
        allow_root=args.allow_root,
        run_tests=args.run_tests,
    )
    print_json({"ok": True, "proposal": proposal})
    return 0


def cmd_skills_reject(args: argparse.Namespace) -> int:
    proposal = service(args).reject_skill(args.proposal_id, reason=args.reason)
    print_json({"ok": True, "proposal": proposal})
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
