from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from noggin import BrainService
from noggin.errors import EmptyContentError, LlmConfigurationError, LlmExtractionError, SkillPatchUnsafeError
from noggin.graph import node_slug
from noggin.providers import ProviderConfig
from noggin.redaction import redact_secrets

from fakes import fake_workers


class BrainCoreTests(unittest.TestCase):
    def test_ingest_and_recall_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db", workers=fake_workers())
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

    def test_ingest_materializes_markdown_graph_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db", workers=fake_workers())
            result = brain.ingest(
                "Decision: local-first brain uses MCP as the host-neutral adapter.",
                source="agent",
                kind="decision",
            )

            graph_dir = Path(result["graph_dir"])
            noggin_node = graph_dir / "nodes" / f"{node_slug('noggin')}.md"
            object_node = graph_dir / "nodes" / f"{node_slug('llm workers arrange memory')}.md"
            index = graph_dir / "index.md"

            self.assertEqual(result["graph_status"], "ok")
            self.assertEqual(result["graph_nodes_updated"], 2)
            self.assertTrue(noggin_node.exists())
            self.assertTrue(object_node.exists())
            self.assertTrue(index.exists())

            text = noggin_node.read_text(encoding="utf-8")
            self.assertIn("# noggin", text)
            self.assertIn("local-first brain uses MCP", text)
            self.assertIn("[[llm-workers-arrange-memory-", text)
            self.assertIn("Evidence:", text)

    def test_duplicate_idempotency_key_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db", workers=fake_workers())
            first = brain.ingest("Lesson: always name the error path.", idempotency_key="same")
            second = brain.ingest("Lesson: always name the error path.", idempotency_key="same")
            self.assertFalse(first["duplicate"])
            self.assertTrue(second["duplicate"])
            self.assertEqual(first["event_id"], second["event_id"])

    def test_empty_input_has_named_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db", workers=fake_workers())
            with self.assertRaises(EmptyContentError):
                brain.ingest("   ")

    def test_secret_redaction(self) -> None:
        redacted = redact_secrets("token sk-thisIsASecretTokenValue123456")
        self.assertIn("openai_key", redacted.findings)
        self.assertNotIn("sk-thisIsASecretTokenValue", redacted.content)

    def test_skill_draft_rejects_unsafe_target_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db", workers=fake_workers())
            with self.assertRaises(LlmExtractionError):
                brain.propose_skill(
                    "Mistake: do not silently edit skill files.",
                    target_path="/tmp/outside/SKILL.md",
                )

    def test_stored_skill_proposal_apply_respects_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db", workers=fake_workers())
            proposal_id = brain.store.create_skill_proposal(
                title="Unsafe proposal",
                reason="Stored proposals still need apply-time safety.",
                target_path="/tmp/outside/SKILL.md",
                patch="",
                new_content="---\nname: unsafe\n---\n",
                metadata={},
            )
            with self.assertRaises(SkillPatchUnsafeError):
                brain.apply_skill(proposal_id, allow_root=Path(tmp) / "allowed")

    def test_skill_proposal_apply_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            brain = BrainService(Path(tmp) / "brain.db", workers=fake_workers())
            proposal = brain.propose_skill(
                "Mistake: run tests after skill proposals.",
                target_path="skills/test/SKILL.md",
            )
            applied = brain.apply_skill(proposal["id"], allow_root=root)
            self.assertEqual(applied["status"], "applied")
            self.assertTrue((root / "skills/test/SKILL.md").exists())

    def test_provider_config_requires_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"NOGGIN_PROVIDER": "openai", "NOGGIN_ENV": str(Path(tmp) / "missing.env")}
            with mock.patch.dict("os.environ", env, clear=True):
                with self.assertRaises(LlmConfigurationError):
                    ProviderConfig.from_env()

    def test_provider_config_loads_user_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "noggin.env"
            env_file.write_text(
                "\n".join(
                    [
                        "NOGGIN_PROVIDER='openai'",
                        "NOGGIN_API_KEY='file-key'",
                        "NOGGIN_MODEL='file-model'",
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"NOGGIN_ENV": str(env_file)}, clear=True):
                config = ProviderConfig.from_env()
            self.assertEqual(config.provider, "openai")
            self.assertEqual(config.api_key, "file-key")
            self.assertEqual(config.model, "file-model")

    def test_user_env_file_does_not_override_process_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "noggin.env"
            env_file.write_text(
                "\n".join(
                    [
                        "NOGGIN_PROVIDER='openai'",
                        "NOGGIN_API_KEY='file-key'",
                    ]
                ),
                encoding="utf-8",
            )
            env = {"NOGGIN_ENV": str(env_file), "NOGGIN_API_KEY": "process-key"}
            with mock.patch.dict("os.environ", env, clear=True):
                config = ProviderConfig.from_env()
            self.assertEqual(config.api_key, "process-key")


if __name__ == "__main__":
    unittest.main()
