#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${1:-/tmp/open-brain-smoke.db}"

rm -f "$DB" "$DB-wal" "$DB-shm"

PYTHONPATH="$ROOT/src" python3 -m open_brain.cli --db "$DB" doctor >/dev/null
PYTHONPATH="$ROOT/src" python3 -m open_brain.cli --db "$DB" ingest \
  --source smoke --kind decision \
  "Decision: smoke test verifies ingest and recall." >/dev/null
PYTHONPATH="$ROOT/src" python3 -m open_brain.cli --db "$DB" recall "smoke ingest recall" >/tmp/open-brain-smoke-result.json
python3 - <<'PY'
import json
from pathlib import Path
data = json.loads(Path("/tmp/open-brain-smoke-result.json").read_text())
assert data["ok"] is True
assert data["results"], "expected at least one recall result"
PY

echo "Open Brain smoke test passed: $DB"

