"""Hermes plugin shim for Open Brain Plugin.

Install:
  1. `pip install -e /path/to/open-brain-plugin`
  2. Copy this directory to `~/.hermes/plugins/open_brain`
  3. `hermes plugins enable open_brain`
"""

from __future__ import annotations

import json
from typing import Any

from open_brain import BrainService

TOOLSET = "open_brain"


INGEST_SCHEMA = {
    "name": "brain_ingest",
    "description": "Store source activity in the local brain with provenance and extraction.",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "source": {"type": "string"},
            "kind": {"type": "string"},
            "workspace": {"type": "string"},
            "actor": {"type": "string"},
            "source_id": {"type": "string"},
            "idempotency_key": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["content"],
    },
}

RECALL_SCHEMA = {
    "name": "brain_recall",
    "description": "Search the local brain and return evidence-backed observations.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
            "workspace": {"type": "string"},
        },
        "required": ["query"],
    },
}

REFLECT_SCHEMA = {
    "name": "brain_reflect",
    "description": "Synthesize matching brain context into compact bullets with provenance.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
            "workspace": {"type": "string"},
        },
        "required": ["query"],
    },
}

SKILL_PROPOSE_SCHEMA = {
    "name": "brain_skill_propose",
    "description": "Create a guarded draft SKILL.md proposal from a mistake or workflow lesson.",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "title": {"type": "string"},
            "target_path": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["content"],
    },
}


def _brain() -> BrainService:
    return BrainService()


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def _brain_ingest(args: dict[str, Any], **_: Any) -> str:
    return _json(
        _brain().ingest(
            args["content"],
            source=args.get("source", "hermes"),
            kind=args.get("kind", "note"),
            workspace=args.get("workspace", "default"),
            actor=args.get("actor", "hermes"),
            source_id=args.get("source_id"),
            idempotency_key=args.get("idempotency_key"),
            metadata=args.get("metadata") or {},
        )
    )


def _brain_recall(args: dict[str, Any], **_: Any) -> str:
    return _json(
        {
            "results": _brain().recall(
                args["query"],
                limit=int(args.get("limit", 10)),
                workspace=args.get("workspace"),
            )
        }
    )


def _brain_reflect(args: dict[str, Any], **_: Any) -> str:
    return _json(
        _brain().reflect(
            args["query"],
            limit=int(args.get("limit", 8)),
            workspace=args.get("workspace"),
        )
    )


def _brain_skill_propose(args: dict[str, Any], **_: Any) -> str:
    return _json(
        _brain().propose_skill(
            args["content"],
            title=args.get("title"),
            target_path=args.get("target_path"),
            reason=args.get("reason"),
        )
    )


def register(ctx) -> None:
    for name, schema, handler in [
        ("brain_ingest", INGEST_SCHEMA, _brain_ingest),
        ("brain_recall", RECALL_SCHEMA, _brain_recall),
        ("brain_reflect", REFLECT_SCHEMA, _brain_reflect),
        ("brain_skill_propose", SKILL_PROPOSE_SCHEMA, _brain_skill_propose),
    ]:
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
            check_fn=lambda: True,
            emoji="",
        )

