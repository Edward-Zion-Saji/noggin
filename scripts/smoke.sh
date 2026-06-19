#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${1:-/tmp/noggin-smoke.db}"
PORT_FILE="$(mktemp)"

rm -f "$DB" "$DB-wal" "$DB-shm"

python3 - "$PORT_FILE" <<'PY' &
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw.decode("utf-8"))
        messages = payload.get("messages", [])
        system = messages[0].get("content", "") if messages else ""
        user = {}
        if messages:
            try:
                user = json.loads(messages[-1].get("content", "{}"))
            except json.JSONDecodeError:
                user = {}
        if "SKILL.md" in system:
            content = {
                "title": "Smoke skill",
                "reason": "Smoke test draft.",
                "target_path": "skills/smoke/SKILL.md",
                "skill_markdown": "---\nname: smoke\n---\n# Smoke\n",
            }
        elif "Synthesize recall results" in system:
            content = {"summary": "- Smoke recall found matching context."}
        else:
            event_content = user.get("content", "")
            content = {
                "observations": [
                    {
                        "kind": user.get("kind_hint", "decision"),
                        "subject": "smoke",
                        "predicate": "verified",
                        "object": "ingest and recall",
                        "content": event_content,
                        "confidence": 0.9,
                        "tags": ["smoke"],
                    }
                ]
            }
        body = json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
Path(sys.argv[1]).write_text(str(server.server_port), encoding="utf-8")
server.serve_forever()
PY
SERVER_PID=$!

cleanup() {
  if kill "$SERVER_PID" >/dev/null 2>&1; then
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$PORT_FILE"
}
trap cleanup EXIT

for _ in $(seq 1 50); do
  if [[ -s "$PORT_FILE" ]]; then
    break
  fi
  sleep 0.1
done

if [[ ! -s "$PORT_FILE" ]]; then
  echo "mock LLM server failed to start" >&2
  exit 1
fi

PORT="$(cat "$PORT_FILE")"
export NOGGIN_PROVIDER=openai
export NOGGIN_API_KEY=smoke
export NOGGIN_BASE_URL="http://127.0.0.1:${PORT}/v1"
export NOGGIN_MODEL=smoke-model

PYTHONPATH="$ROOT/src" python3 -m noggin.cli --db "$DB" doctor >/dev/null
PYTHONPATH="$ROOT/src" python3 -m noggin.cli --db "$DB" ingest \
  --source smoke --kind decision \
  "Decision: smoke test verifies ingest and recall." >/dev/null
PYTHONPATH="$ROOT/src" python3 -m noggin.cli --db "$DB" recall "smoke ingest recall" >/tmp/noggin-smoke-result.json
python3 - <<'PY'
import json
from pathlib import Path
data = json.loads(Path("/tmp/noggin-smoke-result.json").read_text())
assert data["ok"] is True
assert data["results"], "expected at least one recall result"
PY

echo "Noggin smoke test passed: $DB"
