#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

python3 -m pip install -e "$ROOT"

mkdir -p "$HERMES_HOME/skills/noggin"
cp "$ROOT/integrations/hermes/SKILL.md" "$HERMES_HOME/skills/noggin/SKILL.md"

mkdir -p "$HERMES_HOME/plugins/noggin"
cp "$ROOT/integrations/hermes/noggin_plugin/plugin.yaml" "$HERMES_HOME/plugins/noggin/plugin.yaml"
cp "$ROOT/integrations/hermes/noggin_plugin/__init__.py" "$HERMES_HOME/plugins/noggin/__init__.py"

cat <<EOF
Installed Noggin for Hermes.

Skill:
  $HERMES_HOME/skills/noggin/SKILL.md

Plugin:
  $HERMES_HOME/plugins/noggin

Next:
  hermes plugins enable noggin
  hermes
EOF

