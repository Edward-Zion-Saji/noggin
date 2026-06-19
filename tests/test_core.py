from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from noggin import BrainService
from noggin.errors import EmptyContentError, SkillPatchUnsafeError
from noggin.redaction import redact_secrets


class BrainCoreTests(unittest.TestCase):
    def test_ingest_and_recall_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db")
            result = brain.ingest(
                "Decision: local-first brain uses MCP as the host-neutral adapter.",
                source="agent",
                kind="decision",
            )
            self.assertFalse(result["duplicate"])
            self.assertEqual(result["observations_added"], 1)

            recall = brain.recall("host neutral MCP")
            self.assertEqual(len(recall), 1)
            self.assertEqual(recall[0]["kind"], "decision")
            self.assertIn("local-first", recall[0]["content"])

    def test_duplicate_idempotency_key_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db")
            first = brain.ingest("Lesson: always name the error path.", idempotency_key="same")
            second = brain.ingest("Lesson: always name the error path.", idempotency_key="same")
            self.assertFalse(first["duplicate"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(first["event_id"], second["event_id"])

    def test_empty_input_has_named_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db")
            with self.assertRaises(EmptyContentError):
                brain.ingest("   ")

    def test_secret_redaction(self) -> None:
        redacted = redact_secrets("token sk-thisIsASecretTokenValue123456")
        self.assertIn("openai_key", redacted.findings)
        self.assertNotIn("sk-thisIsASecretTokenValue", redacted.content)

    def test_skill_proposal_apply_respects_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db")
            proposal = brain.propose_skill(
                "Mistake: do not silently edit skill files.",
                target_path="/tmp/outside/SKILL.md",
            )
            with self.assertRaises(SkillPatchUnsafeError):
                brain.apply_skill(proposal["id"], allow_root=Path(tmp) / "allowed")

    def test_skill_proposal_apply_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            brain = BrainService(Path(tmp) / "brain.db")
            proposal = brain.propose_skill(
                "Mistake: run tests after skill proposals.",
                target_path="skills/test/SKILL.md",
            )
            applied = brain.apply_skill(proposal["id"], allow_root=root)
            self.assertEqual(applied["status"], "applied")
            self.assertTrue((root / "skills/test/SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()

