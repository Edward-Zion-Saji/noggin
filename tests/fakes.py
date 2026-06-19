from __future__ import annotations

import json


class FakeLlmClient:
    provider = "fake"
    model = "fake-workers"

    def complete_json(self, messages: list[dict[str, str]], *, timeout: float | None = None) -> object:
        system = messages[0]["content"]
        payload = _payload(messages)
        if "SKILL.md" in system:
            target = payload.get("target_path_hint") or "skills/test/SKILL.md"
            title = payload.get("title_hint") or "Run tests after skill proposals"
            reason = payload.get("reason_hint") or "Skill proposal changes need verification before apply."
            return {
                "title": title,
                "reason": reason,
                "target_path": target,
                "skill_markdown": """---
name: run-tests-after-skill-proposals
description: Use when a skill proposal is about to be applied.
version: 1.0.0
author: Noggin
license: MIT
---

# Run Tests After Skill Proposals

## Overview
Use this draft when applying skill changes.

## When to Use
- Before applying a skill proposal.

## Procedure
1. Apply the proposal in an allowed root.
2. Run the relevant tests.

## Common Pitfalls
- Do not skip verification.

## Verification Checklist
- [ ] Tests passed.
""",
            }
        if "Synthesize recall results" in system:
            return {"summary": "- The brain has matching evidence from fake workers."}
        content = str(payload.get("content") or "fake workers arranged this event.")
        kind_hint = str(payload.get("kind_hint") or "note")
        kind = "decision" if content.lower().startswith("decision:") else kind_hint
        return {
            "observations": [
                {
                    "kind": kind,
                    "subject": "noggin",
                    "predicate": "decided",
                    "object": "llm workers arrange memory",
                    "content": content,
                    "confidence": 0.91,
                    "tags": ["decision", "llm"],
                }
            ]
        }


def _payload(messages: list[dict[str, str]]) -> dict[str, object]:
    try:
        data = json.loads(messages[-1]["content"])
    except (KeyError, json.JSONDecodeError, IndexError):
        return {}
    return data if isinstance(data, dict) else {}


def fake_workers():
    from noggin.workers import NogginWorkers

    return NogginWorkers(FakeLlmClient())
