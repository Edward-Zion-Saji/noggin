# Runbook

## Local Health

For guided first-run setup:

```bash
./setup.sh
```

This writes `~/.noggin/noggin.env`, which Noggin auto-loads at runtime.

```bash
export NOGGIN_PROVIDER=openai
export NOGGIN_API_KEY=...
noggin doctor
noggin stats
```

Expected: JSON with `ok: true`, a database path, provider/model details, and
event/observation counts.

## LLM Provider Configuration

Noggin is LLM-only. Configure a provider before running CLI commands or servers:

```bash
export NOGGIN_PROVIDER=openai
export NOGGIN_API_KEY=...
export NOGGIN_MODEL=gpt-4o-mini
```

Use provider-specific key env vars when useful, such as
`NOGGIN_ANTHROPIC_API_KEY`, `NOGGIN_GEMINI_API_KEY`, or
`NOGGIN_OPENROUTER_API_KEY`. For OpenAI-compatible local gateways, set
`NOGGIN_PROVIDER=custom`, `NOGGIN_BASE_URL=http://host:port/v1`, and
`NOGGIN_API_KEY` to the gateway token.

## Slack Adapter

```bash
export NOGGIN_SLACK_SIGNING_SECRET=...
noggin slack serve --host 0.0.0.0 --port 8787
```

Health check:

```bash
curl http://127.0.0.1:8787/health
```

If Slack returns signature errors, verify the app's signing secret, request URL,
and system clock. Slack requests older than five minutes are rejected.

## Sync Peer

```bash
export NOGGIN_SYNC_TOKEN="$(openssl rand -hex 24)"
noggin sync serve --host 0.0.0.0 --port 8797
```

Push from another machine:

```bash
NOGGIN_SYNC_TOKEN=... noggin sync push http://host:8797
```

Pull into another machine:

```bash
NOGGIN_SYNC_TOKEN=... noggin sync pull http://host:8797
```

## Dashboard

```bash
noggin dashboard --open
```

Use the proposals tab for draft skill changes. Apply requires an explicit
allowed root; test commands can be supplied through CLI for safer automation.

## Logs

Default structured log path:

```bash
~/.noggin/logs/brain.log
```

Important events:

- `brain.event.appended`
- `brain.event.duplicate`
- `brain.extraction.failed`
- `brain.skill_proposal.created`
- `brain.skill_proposal.applied`
- `brain.sync.imported`
- `brain.slack.signature_error`
