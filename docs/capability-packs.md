# Capability Packs

Capability Packs are the global, user-data-level container for AI-assisted
capability growth in YuntaoCode.

They are not project files and are not trusted built-in runtime modules. They
live under:

```text
<YuntaoCode data dir>/capability-packs/
  index.json
  items/
    <pack-id>/
      SKILL.md
      examples/
      tests/
  exports/
```

This keeps locally learned capabilities usable across projects, exportable to
other machines or users, and separate from the open-source repository.

## Why Packs Before Plugins

Most useful AI-created capabilities should first become a **method skill**:

- prompts and task framing;
- reusable steps;
- counterexamples and failure modes;
- verification checklists;
- known tool routes;
- evidence requirements.

This is closer to the mainstream `SKILL.md` style, but YuntaoCode treats it as
one kind of runtime asset rather than the whole extension system.

Executable plugins or tool adapters are heavier. They can run code, depend on
packages, call external applications, or modify local state. They must remain
draft descriptors until the runtime has a controlled execution boundary.

## Pack Kinds

`method_skill`
: Model-facing reusable method. This is the default and preferred first form.

`task_template`
: Parameterized task shape or runbook-like workflow. It can seed a normal Run
  but must not become a second execution engine.

`context_pack`
: Curated context digest or domain/project-independent knowledge. It should be
  selected by context policy, not blindly injected.

`tool_adapter`
: Draft descriptor for a new executable capability provider. It is not loaded
  as `runtime.skills.*` and must not run in-process by default.

## Current Implementation

The initial implementation provides:

- pure schema in `runtime/core/capability_pack.py`;
- global store in `runtime/capability_pack_store.py`;
- management API under `/capability-packs`;
- read-only capability-page exposure;
- JSON export bundles containing the manifest and bounded file contents.

It intentionally does not provide:

- automatic execution of generated code;
- automatic registration into `runtime/skills/`;
- remote upload or marketplace behavior;
- automatic promotion into trusted runtime features.

## Export Contract

Export produces `capability_pack_export.v1`:

```json
{
  "schema_version": "capability_pack_export.v1",
  "record_kind": "capability_pack_export",
  "pack": {
    "schema_version": "capability_pack.v1",
    "kind": "method_skill"
  },
  "files": [
    {
      "path": "SKILL.md",
      "encoding": "utf-8",
      "content": "..."
    }
  ],
  "skipped_files": []
}
```

The export bundle is designed for manual sharing, diagnostics, replay research,
and future promotion review. Sharing a bundle should still be treated like
sharing generated code or operational knowledge: review it for secrets and
local paths first.

## Relationship To Skill Evolution

Capability Packs can be outputs of the experience layer:

```text
Runbook evidence
  -> Experience Sample / Digest
  -> Capability Pack draft
  -> Replay / evaluation evidence
  -> manual promotion decision
```

The important boundary is that a pack is evidence-backed reusable knowledge or
a draft descriptor. It is not a permission to mutate core runtime code.

## Relationship To Plugins And MCP

- Built-in tools stay in `runtime/skills/`.
- MCP services stay in `mcp-services/` and the MCP manager.
- External plugins remain a future controlled provider boundary.
- Capability Packs may describe a future provider, but they do not load it.

This lets YuntaoCode learn useful behavior without turning every successful
task into code that can execute inside the main process.
