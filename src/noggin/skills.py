"""Guarded skill proposal and apply workflow."""

from __future__ import annotations

import difflib
import re
import subprocess
from pathlib import Path
from typing import Any

from .errors import SkillPatchConflictError, SkillPatchTestError, SkillPatchUnsafeError
from .models import content_hash
from .observability import log_event, utc_now
from .store import BrainStore


def propose_skill(
    store: BrainStore,
    *,
    content: str,
    title: str | None = None,
    target_path: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Create a draft skill proposal from a lesson or mistake."""

    clean = " ".join(content.split()).strip()
    if not clean:
        raise ValueError("content is required")
    skill_title = title or _title_from_content(clean)
    slug = _slugify(skill_title)
    target = target_path or f"skills/brain-learnings/{slug}/SKILL.md"
    target_file = Path(target).expanduser()
    base_content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
    new_content = _render_skill(skill_title, clean, reason or "Learned from brain activity.")
    patch = "\n".join(
        difflib.unified_diff(
            base_content.splitlines(),
            new_content.splitlines(),
            fromfile=str(target),
            tofile=str(target),
            lineterm="",
        )
    )
    proposal_id = store.create_skill_proposal(
        title=skill_title,
        reason=reason or clean,
        target_path=target,
        patch=patch,
        new_content=new_content,
        metadata={
            "base_hash": content_hash(base_content),
            "created_by": "noggin",
            "created_at": utc_now(),
        },
    )
    return store.get_skill_proposal(proposal_id) or {"id": proposal_id}


def apply_skill_proposal(
    store: BrainStore,
    proposal_id: str,
    *,
    allow_root: str | Path,
    run_tests: str | None = None,
) -> dict[str, Any]:
    """Apply a skill proposal after safety and conflict checks."""

    proposal = store.get_skill_proposal(proposal_id)
    if not proposal:
        raise SkillPatchConflictError(f"proposal not found: {proposal_id}")

    root = Path(allow_root).expanduser().resolve()
    target = Path(proposal["target_path"]).expanduser()
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    if not _is_relative_to(target, root):
        store.set_skill_proposal_status(
            proposal_id,
            "quarantined",
            {"failure": "target_outside_allow_root", "target": str(target), "allow_root": str(root)},
        )
        raise SkillPatchUnsafeError(f"target {target} is outside allowed root {root}")

    current = target.read_text(encoding="utf-8") if target.exists() else ""
    expected_hash = proposal.get("metadata", {}).get("base_hash")
    if expected_hash and content_hash(current) != expected_hash:
        store.set_skill_proposal_status(
            proposal_id,
            "conflicted",
            {"failure": "base_hash_mismatch", "target": str(target)},
        )
        raise SkillPatchConflictError(f"target changed since proposal was created: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    backup = current
    existed = target.exists()
    target.write_text(proposal["new_content"], encoding="utf-8")
    try:
        test_result = None
        if run_tests:
            test_result = subprocess.run(
                run_tests,
                cwd=str(root),
                shell=True,
                text=True,
                capture_output=True,
                timeout=600,
            )
            if test_result.returncode != 0:
                if existed:
                    target.write_text(backup, encoding="utf-8")
                else:
                    target.unlink(missing_ok=True)
                store.set_skill_proposal_status(
                    proposal_id,
                    "failed",
                    {
                        "failure": "tests_failed",
                        "stdout": test_result.stdout[-4000:],
                        "stderr": test_result.stderr[-4000:],
                    },
                )
                raise SkillPatchTestError(f"tests failed for proposal {proposal_id}")
        store.set_skill_proposal_status(
            proposal_id,
            "applied",
            {
                "target": str(target),
                "test_command": run_tests,
                "test_stdout": (test_result.stdout[-4000:] if test_result else ""),
                "test_stderr": (test_result.stderr[-4000:] if test_result else ""),
            },
        )
        log_event("brain.skill_proposal.applied", proposal_id=proposal_id, target=str(target))
        return store.get_skill_proposal(proposal_id) or proposal
    except SkillPatchTestError:
        raise


def reject_skill_proposal(store: BrainStore, proposal_id: str, *, reason: str = "") -> dict[str, Any]:
    """Reject a proposal without applying it."""

    store.set_skill_proposal_status(proposal_id, "rejected", {"reject_reason": reason})
    proposal = store.get_skill_proposal(proposal_id)
    if not proposal:
        raise SkillPatchConflictError(f"proposal not found: {proposal_id}")
    return proposal


def _render_skill(title: str, lesson: str, reason: str) -> str:
    name = _slugify(title)[:64].strip("-") or "brain-learned-skill"
    description = f"Use when this recurring lesson applies: {lesson[:180]}"
    return f"""---
name: {name}
description: "{_yaml_quote(description[:900])}"
version: 1.0.0
author: Noggin
license: MIT
metadata:
  noggin:
    generated: true
    reason: "{_yaml_quote(reason[:300])}"
---

# {title}

## Overview

This skill was proposed by Noggin from observed activity. Treat it as
a draft until a human or trusted agent verifies that the lesson is generally
useful and not just an artifact of one session.

## When to Use

- Use when the current task resembles this learned lesson:
  `{lesson}`
- Use when preventing the same mistake would materially reduce rework.

## Procedure

1. Check whether the triggering context truly matches this lesson.
2. Apply the smallest explicit change that prevents the mistake.
3. Verify the result with a concrete test or reproduction.
4. Record whether the lesson helped so the brain can update confidence.

## Common Pitfalls

- Do not blindly apply this skill when provenance is weak.
- Do not treat a one-off failure as a universal rule.
- Do not edit critical files without a rollback path.

## Verification Checklist

- [ ] Source evidence was reviewed.
- [ ] The change is scoped to the actual failure.
- [ ] Tests or a manual verification step passed.
"""


def _title_from_content(content: str) -> str:
    first = re.split(r"[.!?\n]", content, maxsplit=1)[0].strip()
    if not first:
        return "Brain Learned Skill"
    return first[:80].rstrip(":")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "brain-learned-skill"


def _yaml_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
