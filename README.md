# Noggin

Noggin is a local-first brain for humans, teams, and AI agents.
It ingests surface activity from Slack, agent sessions, GitHub, and direct CLI
input; extracts durable observations; stores provenance in SQLite; and exposes
the brain through CLI, MCP, Hermes, OpenClaw, a Slack slash command, and a small
dashboard.

The product goal is simple: every useful mistake, decision, process detail, and
workflow lesson should become reusable context instead of disappearing at the
end of a chat.

## V1 Surface Map

```
Slack / GitHub / Agent / CLI
          │
          ▼
  source event envelope
          │
          ▼
 validate -> redact -> dedupe -> extract
          │                    │
          ▼                    ▼
 append-only event log   observations + entities + edges
          │                    │
          └────────► local SQLite brain ◄──────── skill proposals
                                │
                                ▼
             CLI + MCP + Hermes + OpenClaw + dashboard
```

## Install

```bash
git clone <this-repo>
cd noggin
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
noggin doctor
```

No LLM key is required. Without a key, the extractor uses deterministic rules.
With an OpenAI-compatible endpoint configured, it can extract richer facts:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4o-mini
# Optional: export OPENAI_BASE_URL=https://api.openai.com/v1
```

## Quick Start

```bash
noggin ingest "Decision: we keep the first version local-first and use MCP as the host-neutral adapter."
noggin ingest --source agent --kind mistake "Mistake: auto-editing skills silently breaks trust. Always create a proposal first."
noggin recall "local-first adapter"
noggin skills propose --content "Mistake: deployment failed because migrations were not listed in the release checklist."
noggin dashboard --open
```

## Adapters

### Local Install For Hermes

```bash
scripts/install-hermes.sh
hermes plugins enable noggin
```

### Local Install For OpenClaw

```bash
scripts/install-openclaw.sh
```

### MCP

```bash
noggin mcp
```

Expose this command as a stdio MCP server. It supports:

- `brain_ingest`
- `brain_recall`
- `brain_reflect`
- `brain_skill_propose`

### Slack

```bash
export NOGGIN_SLACK_SIGNING_SECRET=...
noggin slack serve --port 8787
```

Configure a Slack slash command to POST to `/slack/command`.

Supported slash command text:

- `remember <text>`
- `recall <query>`
- `propose-skill <mistake or workflow lesson>`
- `status`

### GitHub

```bash
noggin github issue owner/repo 123
noggin github pr owner/repo 456
```

Set `GITHUB_TOKEN` for private repositories or higher rate limits.

### Hermes and OpenClaw

Install the generated skill files from `integrations/hermes/SKILL.md` or
`integrations/openclaw/SKILL.md`. Hermes can also load the plugin in
`integrations/hermes/noggin_plugin/`.

## Skill Proposal Safety

The brain never silently edits skills by default. It creates a proposal with
provenance and an explicit target path. Applying a proposal requires an allowed
root and writes an audit event. If `--run-tests` is provided, the proposal is
rolled back when tests fail.

## Storage

Default database path:

```bash
~/.noggin/brain.db
```

Override with:

```bash
export NOGGIN_DB=/path/to/brain.db
```

## Development

```bash
python -m pytest
ruff check .
```
