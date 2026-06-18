#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"

python3 -m pip install -e "$ROOT"

mkdir -p "$OPENCLAW_HOME/skills/open-brain"
cp "$ROOT/integrations/openclaw/SKILL.md" "$OPENCLAW_HOME/skills/open-brain/SKILL.md"

cat <<EOF
Installed Open Brain for OpenClaw.

Skill:
  $OPENCLAW_HOME/skills/open-brain/SKILL.md

MCP server command:
  brain mcp

Add that command to your OpenClaw MCP/tool server configuration if your
OpenClaw setup does not auto-discover stdio MCP servers.
EOF

