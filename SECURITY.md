# Security

## Threat Model

Noggin ingests untrusted content from humans, agents, Slack, GitHub,
and future surfaces. The main threats are prompt injection, secret capture,
cross-workspace leakage, silent data loss, and unsafe skill mutation.

## Guardrails

- External content is stored as data, never instructions.
- Secrets are redacted before extraction and persisted redacted by default.
- Each event includes workspace/profile/source provenance.
- Duplicate retries use idempotency keys and content hashes.
- Skill proposals must target an explicitly allowed root before apply.
- Apply operations can run tests and roll back on failure.
- Slack requests can be verified with the Slack signing secret.
- Sync endpoints require bearer-token auth.

## Reporting

This is an early open-source V1. File security issues privately with the repo
maintainers until a public disclosure process exists.

