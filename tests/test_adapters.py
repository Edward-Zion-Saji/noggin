from __future__ import annotations

import hashlib
import hmac
import tempfile
import time
import unittest
from pathlib import Path

from open_brain import BrainService
from open_brain.mcp_server import McpServer
from open_brain.slack import handle_slack_command, verify_slack_signature
from open_brain.sync import export_snapshot, import_snapshot


class AdapterTests(unittest.TestCase):
    def test_mcp_tool_call_ingests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = McpServer(BrainService(Path(tmp) / "brain.db"))
            response = server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "brain_ingest",
                        "arguments": {"content": "Decision: MCP calls ingest correctly."},
                    },
                }
            )
            text = response["result"]["content"][0]["text"]
            self.assertIn("event_id", text)

    def test_slack_remember_and_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brain = BrainService(Path(tmp) / "brain.db")
            remembered = handle_slack_command(
                brain,
                {
                    "text": "remember Decision: Slack slash command stores context.",
                    "team_id": "T1",
                    "user_id": "U1",
                    "channel_id": "C1",
                    "trigger_id": "TR1",
                },
            )
            self.assertIn("Remembered", remembered["text"])
            recalled = handle_slack_command(
                brain,
                {
                    "text": "recall slash command",
                    "team_id": "T1",
                    "user_id": "U1",
                    "channel_id": "C1",
                    "trigger_id": "TR2",
                },
            )
            self.assertIn("Slack slash command", recalled["text"])

    def test_slack_signature_verification(self) -> None:
        secret = "secret"
        body = b"text=status"
        ts = str(int(time.time()))
        signature = "v0=" + hmac.new(
            secret.encode("utf-8"),
            b"v0:" + ts.encode("utf-8") + b":" + body,
            hashlib.sha256,
        ).hexdigest()
        verify_slack_signature(
            signing_secret=secret,
            timestamp=ts,
            signature=signature,
            body=body,
            now=int(ts),
        )

    def test_snapshot_sync_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = BrainService(Path(tmp) / "source.db")
            target = BrainService(Path(tmp) / "target.db")
            source.ingest("Decision: snapshot sync roundtrip works.")
            snapshot = export_snapshot(source.store)
            counts = import_snapshot(target.store, snapshot)
            self.assertEqual(counts["events"], 1)
            self.assertEqual(len(target.recall("snapshot roundtrip")), 1)


if __name__ == "__main__":
    unittest.main()

