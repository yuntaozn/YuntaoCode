# Persistence Model

YuntaoCode is a local-first Task Runtime. Its persistence layer must preserve
task state, trace, audit, recovery, and user data without making the runtime
depend on one storage format.

## Current Boundary

Runtime code accesses persisted operational data through Store classes:

- `TaskStore` owns ToolTask records and logs.
- `RunStore` owns runs and run events.
- `ProductTaskStore` owns product-level Tasks, recovery Checkpoints, and Context
  Snapshots in the operational SQLite database.
- `ConversationStore` owns conversations and messages.
- `MemoryStore` owns reusable memory records.

These Store APIs are the runtime-facing repository boundary. Callers should not
read or write their backing files directly.

The runtime currently uses a mixed backend:

- `RunStore` uses the indexed SQLite database `runtime.db` for runs and run
  events.
- `ProductTaskStore` uses the same operational database for Task relationships
  and recovery artifacts; ToolTask records remain a separate local store.
- `TaskStore`, `ConversationStore`, and `MemoryStore` still use compatible JSON
  documents through the shared `AtomicJsonDocumentStorage` adapter.

The Store API remains stable across those backends.

Conversation messages are a display and follow-up context record, not a second
RunEvent archive. Assistant-message metadata preserves visible process state
such as tool events, plans, reasoning history, change summaries, the task
contract, and a lineage-safe RunResult. Full Context Packs, capability
snapshots, preflight records, route evidence, and completion evidence remain in
the RunEvent repository; conversation metadata keeps bounded Context and
capability summaries where they help display and omits the other duplicate
records. This keeps chat restoration useful without duplicating the complete
audit trace in `conversations.json`.

## Run Repository

`RunStore` owns run lifecycle and event-driven state transitions.
`RunRepository` owns persistence only:

- `SqliteRunRepository` stores runs and run events in separate tables.
- run creation, state update, and event append use transactions;
- workspace, conversation, status, and run-event sequence queries are indexed;
- retention removes old runs and old per-run events without rewriting history;
- list queries read run summaries and event counts without loading event
  payloads;
- detail queries load one run and its retained events.

On first startup with `runtime.db`, a valid historical `runs.json` is imported
once. The source JSON file is retained unchanged as a migration snapshot. New
runs are written only to SQLite.

## Data Classes

Different kinds of local data have different persistence needs:

- Small configuration documents such as settings, workspace roots, and MCP
  service definitions can remain JSON because users may inspect or edit them.
- Operational records such as conversations, messages, runs, run events,
  ToolTasks, task logs, and memories need indexed queries and transactional
  updates as their volume grows.
- Large generated artifacts, exports, screenshots, and temporary run assets
  should remain files referenced by structured metadata.

## Why Operational JSON Does Not Scale

The current operational stores serialize a complete document after changes.
That keeps alpha data easy to inspect, but it creates write amplification,
increasing parse costs, weak concurrent-write behavior, and a larger corruption
blast radius as history grows.

Atomic replacement prevents partially written JSON files. It does not solve
whole-document rewrite cost or indexed querying.

## Target Direction

The operational backend is moving incrementally to SQLite while Store APIs
remain stable.
The conceptual schema should separate at least:

- conversations and messages
- runs and run events
- product tasks, plans, and steps
- ToolTasks and task logs
- memories
- artifact metadata

SQLite tables should use explicit schema versions, transactions, foreign keys,
and indexes for common workspace, conversation, run, status, and time queries.
Artifact contents should not be embedded in the database by default.

## Current Migration State

1. **Shared JSON mechanics - complete:** use one atomic document adapter while
   preserving existing Store APIs and JSON formats.
2. **Operational SQLite backend - in progress:** Run/RunEvent are the first
   transactional, indexed repository. Other operational stores remain JSON
   until their schemas and migration paths are designed.
3. **Migration and maintenance:** add backup, import/export, JSON-to-SQLite
   migration, retention, and trace pruning policies.

Each SQLite adoption must include migration tests and a rollback or backup
path. The retained `runs.json` is a pre-migration snapshot, not a live mirror
of new SQLite run history.
