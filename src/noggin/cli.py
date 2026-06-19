"""Command-line interface for Noggin."""

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
    parser = argparse.ArgumentParser(prog="noggin", description="Local-first brain for agents and teams.")
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

    mcp = sub.add_parser("mcp", help="Run the stdio MCP server.")
    mcp.set_defaults(func=cmd_mcp)

    slack = sub.add_parser("slack", help="Slack adapter commands.")
    slack_sub = slack.add_subparsers(dest="slack_command", required=True)
    slack_serve = slack_sub.add_parser("serve", help="Serve Slack slash-command endpoint.")
    slack_serve.add_argument("--host", default="127.0.0.1")
    slack_serve.add_argument("--port", type=int, default=8787)
    slack_serve.add_argument("--signing-secret")
    slack_serve.set_defaults(func=cmd_slack_serve)

    github = sub.add_parser("github", help="GitHub ingestion commands.")
    github_sub = github.add_subparsers(dest="github_command", required=True)
    github_issue = github_sub.add_parser("issue", help="Ingest a GitHub issue and comments.")
    github_issue.add_argument("repo", help="owner/repo")
    github_issue.add_argument("number", type=int)
    github_issue.add_argument("--token")
    github_issue.set_defaults(func=cmd_github_issue)

    github_pr = github_sub.add_parser("pr", help="Ingest a GitHub pull request.")
    github_pr.add_argument("repo", help="owner/repo")
    github_pr.add_argument("number", type=int)
    github_pr.add_argument("--token")
    github_pr.add_argument("--include-diff", action="store_true")
    github_pr.set_defaults(func=cmd_github_pr)

    sync = sub.add_parser("sync", help="Snapshot and peer sync commands.")
    sync_sub = sync.add_subparsers(dest="sync_command", required=True)
    sync_export = sync_sub.add_parser("export", help="Export local brain snapshot.")
    sync_export.add_argument("output")
    sync_export.set_defaults(func=cmd_sync_export)
    sync_import = sync_sub.add_parser("import", help="Import a brain snapshot.")
    sync_import.add_argument("input")
    sync_import.set_defaults(func=cmd_sync_import)
    sync_serve = sync_sub.add_parser("serve", help="Serve token-protected sync endpoint.")
    sync_serve.add_argument("--host", default="127.0.0.1")
    sync_serve.add_argument("--port", type=int, default=8797)
    sync_serve.add_argument("--token")
    sync_serve.set_defaults(func=cmd_sync_serve)
    sync_push = sync_sub.add_parser("push", help="Push local snapshot to peer URL.")
    sync_push.add_argument("url")
    sync_push.add_argument("--token")
    sync_push.set_defaults(func=cmd_sync_push)
    sync_pull = sync_sub.add_parser("pull", help="Pull peer snapshot into local brain.")
    sync_pull.add_argument("url")
    sync_pull.add_argument("--token")
    sync_pull.set_defaults(func=cmd_sync_pull)

    dashboard = sub.add_parser("dashboard", help="Run the local browser dashboard.")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8790)
    dashboard.add_argument("--open", action="store_true")
    dashboard.set_defaults(func=cmd_dashboard)

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
        "provider": brain.workers.provider,
        "model": brain.workers.model,
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


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import run_mcp

    run_mcp(db_path=args.db)
    return 0


def cmd_slack_serve(args: argparse.Namespace) -> int:
    from .slack import serve_slack

    return serve_slack(args)


def cmd_github_issue(args: argparse.Namespace) -> int:
    from .github import ingest_issue

    return ingest_issue(args)


def cmd_github_pr(args: argparse.Namespace) -> int:
    from .github import ingest_pr

    return ingest_pr(args)


def cmd_sync_export(args: argparse.Namespace) -> int:
    from .sync import cmd_sync_export as run

    return run(args)


def cmd_sync_import(args: argparse.Namespace) -> int:
    from .sync import cmd_sync_import as run

    return run(args)


def cmd_sync_serve(args: argparse.Namespace) -> int:
    from .sync import cmd_sync_serve as run

    return run(args)


def cmd_sync_push(args: argparse.Namespace) -> int:
    from .sync import cmd_sync_push as run

    return run(args)


def cmd_sync_pull(args: argparse.Namespace) -> int:
    from .sync import cmd_sync_pull as run

    return run(args)


def cmd_dashboard(args: argparse.Namespace) -> int:
    from .dashboard import serve_dashboard

    return serve_dashboard(args)


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
