# Runbook

## Local Health

```bash
brain doctor
brain stats
```

Expected: JSON with `ok: true`, a database path, and event/observation counts.

## Slack Adapter

```bash
export BRAIN_SLACK_SIGNING_SECRET=...
brain slack serve --host 0.0.0.0 --port 8787
```

Health check:

```bash
curl http://127.0.0.1:8787/health
```

If Slack returns signature errors, verify the app's signing secret, request URL,
and system clock. Slack requests older than five minutes are rejected.

## Sync Peer

```bash
export BRAIN_SYNC_TOKEN="$(openssl rand -hex 24)"
brain sync serve --host 0.0.0.0 --port 8797
```

Push from another machine:

```bash
BRAIN_SYNC_TOKEN=... brain sync push http://host:8797
```

Pull into another machine:

```bash
BRAIN_SYNC_TOKEN=... brain sync pull http://host:8797
```

## Dashboard

```bash
brain dashboard --open
```

Use the proposals tab for draft skill changes. Apply requires an explicit
allowed root; test commands can be supplied through CLI for safer automation.

## Logs

Default structured log path:

```bash
~/.open-brain/logs/brain.log
```

Important events:

- `brain.event.appended`
- `brain.event.duplicate`
- `brain.extraction.failed`
- `brain.skill_proposal.created`
- `brain.skill_proposal.applied`
- `brain.sync.imported`
- `brain.slack.signature_error`

