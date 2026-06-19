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
  │
  ▼
KnowledgeGraphWriter.sync_nodes()
  │
  ├── node write failure -> GraphWriteError + visible graph_failed status
  ├── index.md
  └── nodes/<slug>.md with observations, links, backlinks, provenance
```

## Knowledge Arrangement Strategy

Noggin Workers use the LLM to decide what belongs in memory. The worker returns
observations shaped as:

```
{
  "kind": "decision|mistake|process|fact|preference|question|lesson",
  "subject": "entity or concept",
  "predicate": "relationship",
  "object": "linked entity or concept",
  "content": "source-grounded observation",
  "confidence": 0.0-1.0,
  "tags": ["..."]
}
```

That becomes a graph:

```
             evidence event
                  │
                  ▼
  subject node -- predicate --> object node
       │                            │
       └──── Markdown node files ───┘
```

SQLite is the source of truth for events, observations, entities, and edges.
Markdown is the durable human surface: every entity becomes one file in
`NOGGIN_GRAPH_DIR/nodes/`, and each file contains outgoing links, incoming
backlinks, observations, and provenance.

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

## Markdown Graph Layout

```
~/.noggin/graph/
  index.md
  nodes/
    noggin-<hash>.md
    llm-workers-<hash>.md
```

Each node is safe to read and link from Markdown tools. Noggin rewrites node
files from SQLite when `noggin graph sync` runs or new observations arrive.

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
