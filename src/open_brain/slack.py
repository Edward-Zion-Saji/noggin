"""Slack slash-command adapter."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

from .brain import BrainService
from .errors import SlackSignatureError
from .models import content_hash
from .observability import log_event


def serve_slack(args: argparse.Namespace) -> int:
    """Run the Slack adapter HTTP server."""

    brain = BrainService(db_path=args.db)
    signing_secret = args.signing_secret or os.getenv("BRAIN_SLACK_SIGNING_SECRET", "")
    handler_cls = _handler(brain, signing_secret)
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)
    print(f"Slack brain adapter listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def handle_slack_command(brain: BrainService, form: dict[str, str]) -> dict[str, Any]:
    """Handle one normalized Slack slash-command payload."""

    text = form.get("text", "").strip()
    team = form.get("team_id") or form.get("team_domain") or "slack"
    actor = form.get("user_id") or form.get("user_name") or "unknown"
    channel = form.get("channel_id") or form.get("channel_name") or "unknown"
    trigger = form.get("trigger_id") or content_hash(json.dumps(form, sort_keys=True))
    if not text or text in {"help", "-h", "--help"}:
        return _slack_text(
            "Open Brain commands: `remember <text>`, `recall <query>`, "
            "`propose-skill <lesson>`, `status`."
        )

    command, _, rest = text.partition(" ")
    command = command.lower()
    rest = rest.strip()
    if command == "remember":
        if not rest:
            return _slack_text("Nothing to remember. Usage: `remember <text>`")
        result = brain.ingest(
            rest,
            source="slack",
            kind="message",
            workspace=team,
            actor=actor,
            source_id=f"{channel}:{trigger}",
            idempotency_key=f"slack:{team}:{channel}:{actor}:{trigger}:{content_hash(rest)}",
            metadata={"channel": channel, "command": "remember"},
        )
        return _slack_text(
            f"Remembered. Event `{result['event_id']}`, observations: "
            f"{result['observations_added']}, duplicate: {result['duplicate']}."
        )

    if command == "recall":
        if not rest:
            return _slack_text("Recall needs a query. Usage: `recall <query>`")
        results = brain.recall(rest, workspace=team, limit=5)
        if not results:
            return _slack_text("No matching brain context found.")
        lines = ["Top brain matches:"]
        for item in results:
            lines.append(f"- `{item.get('kind')}` {item.get('content')} ({item.get('source')})")
        return _slack_text("\n".join(lines))

    if command == "propose-skill":
        if not rest:
            return _slack_text("Skill proposal needs a lesson. Usage: `propose-skill <lesson>`")
        proposal = brain.propose_skill(rest)
        brain.ingest(
            f"Skill proposal created: {proposal['title']}",
            source="slack",
            kind="skill_proposal",
            workspace=team,
            actor=actor,
            source_id=f"{channel}:{trigger}:skill",
            metadata={"proposal_id": proposal["id"]},
        )
        return _slack_text(f"Created skill proposal `{proposal['id']}`: {proposal['title']}")

    if command == "status":
        stats = brain.stats()
        return _slack_text(
            f"Brain status: {stats['events']} events, {stats['observations']} observations, "
            f"{stats['entities']} entities, {stats['skill_proposals']} skill proposals."
        )

    return _slack_text(f"Unknown brain command `{command}`. Try `help`.")


def verify_slack_signature(
    *,
    signing_secret: str,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    now: float | None = None,
) -> None:
    """Verify Slack v0 request signature."""

    if not signing_secret:
        return
    if not timestamp or not signature:
        raise SlackSignatureError("missing Slack signature headers")
    current = now if now is not None else time.time()
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise SlackSignatureError("invalid Slack timestamp") from exc
    if abs(current - ts) > 60 * 5:
        raise SlackSignatureError("stale Slack request timestamp")
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    expected = "v0=" + hmac.new(signing_secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise SlackSignatureError("invalid Slack signature")


def _handler(brain: BrainService, signing_secret: str) -> type[BaseHTTPRequestHandler]:
    class SlackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._json({"ok": True, "adapter": "slack"})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/slack/command":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                verify_slack_signature(
                    signing_secret=signing_secret,
                    timestamp=self.headers.get("X-Slack-Request-Timestamp"),
                    signature=self.headers.get("X-Slack-Signature"),
                    body=body,
                )
                parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                form = {key: values[-1] for key, values in parsed.items()}
                self._json(handle_slack_command(brain, form))
            except SlackSignatureError as exc:
                log_event("brain.slack.signature_error", error=str(exc))
                self._json(_slack_text("Slack signature verification failed."), status=401)
            except Exception as exc:  # process boundary: convert to visible Slack response
                log_event("brain.slack.error", error=str(exc))
                self._json(_slack_text(f"Brain command failed: {exc}"), status=500)

        def log_message(self, format: str, *args: Any) -> None:
            log_event("brain.slack.http", message=format % args)

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return SlackHandler


def _slack_text(text: str) -> dict[str, Any]:
    return {"response_type": "ephemeral", "text": text}

