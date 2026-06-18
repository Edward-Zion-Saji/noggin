#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

python3 -m pip install -e "$ROOT"

mkdir -p "$HERMES_HOME/skills/open-brain"
cp "$ROOT/integrations/hermes/SKILL.md" "$HERMES_HOME/skills/open-brain/SKILL.md"

mkdir -p "$HERMES_HOME/plugins/open_brain"
cp "$ROOT/integrations/hermes/brain_plugin/plugin.yaml" "$HERMES_HOME/plugins/open_brain/plugin.yaml"
cp "$ROOT/integrations/hermes/brain_plugin/__init__.py" "$HERMES_HOME/plugins/open_brain/__init__.py"

cat <<EOF
Installed Open Brain for Hermes.

Skill:
  $HERMES_HOME/skills/open-brain/SKILL.md

Plugin:
  $HERMES_HOME/plugins/open_brain

Next:
  hermes plugins enable open_brain
  hermes
EOF

