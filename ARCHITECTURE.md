# Architecture

## Product Boundary

Open Brain Plugin is not a chat app, not a hosted knowledge base, and not a
replacement for agent skills. It is the durable brain beneath those surfaces.

V1 ships as one Python package with local SQLite storage and adapters around it:

```
                      ┌──────────────┐
                      │  Dashboard   │
                      └──────┬───────┘
                             │
┌────────┐   ┌────────┐   ┌──▼───┐   ┌──────┐   ┌─────────┐
│ Slack  ├──►│ Ingest ├──►│ Core │◄──┤ MCP  │◄──┤ Agents  │
└────────┘   └────────┘   └──┬───┘   └──────┘   └─────────┘
                             │
┌────────┐   ┌────────┐      │       ┌──────────────┐
│ GitHub ├──►│ Events ├──────┴──────►│ Skill Review │
└────────┘   └────────┘              └──────────────┘
```

## Data Flow

```
Raw input
  │
  ├── nil / empty / oversized checks
  ├── secret redaction
  ├── idempotency hash
  ▼
EventLog.append()
  │
  ├── duplicate -> existing event id
  ├── write error -> named failure + log
  ▼
Extractor.extract()
  │
  ├── heuristic extractor if no LLM key
  ├── OpenAI-compatible extractor if configured
  └── extraction failure still leaves raw event stored
  ▼
ObservationStore.upsert()
  │
  ├── entities
  ├── edges
  └── FTS indexes
```

## Skill Patch State Machine

```
draft
  │
  ├── reject ───────────► rejected
  │
  ├── safety failure ───► quarantined
  │
  └── apply request
          │
          ├── target outside allow root ─► quarantined
          ├── patch conflict ───────────► conflicted
          ├── tests fail ───────────────► failed + rollback
          └── tests pass/no tests ──────► applied
```

## Error Philosophy

Every failure has a named exception. Raw events are stored before LLM work so
model failures do not erase evidence. Catch-all exception handlers exist only at
process boundaries where they convert unknown failures into visible JSON/logged
errors.

## Trust Model

All external content is untrusted data. Slack messages, GitHub comments, and
agent transcripts can create observations, but they cannot become system
instructions. Skill edits are proposals until explicitly applied through an
allowed root.

