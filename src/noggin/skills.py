"""Guarded skill proposal and apply workflow."""

from __future__ import annotations

import difflib
import subprocess
from pathlib import Path
from typing import Any

from .errors import SkillPatchConflictError, SkillPatchTestError, SkillPatchUnsafeError
from .models import content_hash
from .observability import log_event, utc_now
from .store import BrainStore
from .workers import SkillDraft


def propose_skill(
    store: BrainStore,
    *,
    draft: SkillDraft,
) -> dict[str, Any]:
    """Create a draft skill proposal from an LLM-generated skill draft."""

    target = draft.target_path
    target_file = Path(target).expanduser()
    base_content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
    patch = "\n".join(
        difflib.unified_diff(
            base_content.splitlines(),
            draft.new_content.splitlines(),
            fromfile=str(target),
            tofile=str(target),
            lineterm="",
        )
    )
    proposal_id = store.create_skill_proposal(
        title=draft.title,
        reason=draft.reason,
        target_path=target,
        patch=patch,
        new_content=draft.new_content,
        metadata={
            "base_hash": content_hash(base_content),
            "created_by": "noggin",
            "drafted_by": "noggin-workers",
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


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
