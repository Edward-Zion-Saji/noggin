# Architecture

## Product Boundary

Noggin is not a chat app, not a hosted knowledge base, and not a
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
NogginWorkers.arrange_event()
  │
  ├── missing API key -> LlmConfigurationError before work starts
  ├── provider timeout/network failure -> LlmExtractionError
  ├── malformed model JSON -> LlmExtractionError
  └── worker failure still leaves raw event stored
  ▼
ObservationStore.upsert()
  │
  ├── entities
  ├── edges
  └── FTS indexes
```

## Provider Graph

```
CLI / Slack / MCP / Dashboard
          │
          ▼
    BrainService
          │
          ▼
   Noggin Workers
          │
          ├── openai/openrouter/groq/together/mistral/ollama/custom
          │       └── OpenAI-compatible chat completions
          ├── anthropic
          │       └── Messages API
          └── gemini
                  └── generateContent API
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

Every failure has a named exception. Raw events are stored before Noggin Workers
arrange memory so model failures do not erase evidence. Process-boundary
handlers convert failures into visible JSON/logged errors.

## Trust Model

All external content is untrusted data. Slack messages, GitHub comments, and
agent transcripts can create observations, but they cannot become system
instructions. Skill edits are proposals until explicitly applied through an
allowed root.
