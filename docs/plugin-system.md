# Runtime Extension Contract Draft

This document defines the early plugin direction for YuntaoCode as a Task Runtime extension contract.

The current release only groups built-in tools by tool ID prefix, such as `filesystem`, `code`, `shell`, `git`, and `web`. These groups are local runtime capabilities, not third-party plugins yet. External plugin loading, remote indexes, auto-update, and marketplace distribution are intentionally out of scope until the Task Runtime contract is stable.

Plugins are capability providers for the Task Runtime. They can expose tools, dependencies, and permission needs, but task state, plan execution, trace, recovery, and audit remain runtime-level concerns.

In the runtime architecture, a plugin should first be understood as a provider
of Capability Contracts. The model may propose using a capability, but the
runtime validates the capability, tool IDs, permissions, confirmations, and
artifacts before execution. See [capability-router.md](capability-router.md).

## Current Boundary

- Built-in capabilities are registered from `runtime/skills/`.
- The current `/plugins` API displays built-in capability groups and their dependency status.
- External plugin manifests are design-stage only.
- Contract examples are documented in this file only; the repository does not ship external plugin sample directories at this stage.
- AI-built plugin drafts belong under the local data directory `ai-plugins/` and are displayed as drafts only.
- AI-built plugin drafts are not Python skill modules. They must not be imported through `runtime.skills.*` or registered by editing `runtime/skills/__init__.py`.

## Goals

- Define how an external capability should describe itself before it can be loaded.
- Make filesystem, shell, network, and model permissions visible before execution.
- Keep tool calls inside the normal Task Runtime path, including confirmation, trace, recovery, and audit.
- Let dependency problems degrade one plugin instead of breaking the runtime.
- Avoid coupling the core runtime to any single application domain, such as video, office documents, RAG, or browser automation.

## Non-Goals for the Current Stage

- Remote plugin marketplace.
- Background auto-update.
- Server-side plugin management.
- Running untrusted plugin code without user review.
- Enterprise policy distribution.
- Default bundling of domain-heavy plugins.

## Contract Shape

AI-built plugin drafts should live under a user-controlled local data directory:

```text
<YuntaoCode data dir>/ai-plugins/
  example-draft/
    plugin.json
    README.md
    src/
    tests/
```

## Draft Manifest

```json
{
  "schema_version": "0.1-draft",
  "id": "example",
  "name": "Example Plugin",
  "version": "0.1.0",
  "description": "Adds example local tools.",
  "entrypoint": "plugin.py",
  "runtime": {
    "loadable": false,
    "stage": "contract_sample"
  },
  "permissions": {
    "filesystem": "workspace",
    "shell": "confirm_each",
    "network": false,
    "model": false
  },
  "dependencies": {
    "python": ">=3.10",
    "node": null,
    "binaries": [],
    "packages": []
  },
  "tools": [
    {
      "id": "example.echo",
      "name": "Echo",
      "description": "Echo input text.",
      "capability": "example.echo",
      "artifacts": [],
      "long_running": false,
      "retry_safe": true,
      "requires_confirmation": false,
      "local_only": true
    }
  ]
}
```

## Permission Model

Initial permission levels should stay intentionally small:

- `filesystem`: `none`, `workspace`, or `full_local`.
- `shell`: `false`, `confirm_each`, or `allow`.
- `network`: `false`, `confirm_each`, or `allow`.
- `model`: `false`, `confirm_each`, or `allow`.

Write tools, shell tools, Git commit tools, export tools, and tools that modify external state should keep confirmation even when the plugin is enabled.

## AI-built Draft Flow

AI can create plugin drafts, but the draft must stay isolated:

1. The user explicitly asks for a new plugin, skill, or reusable capability.
2. AI creates a draft under `<YuntaoCode data dir>/ai-plugins/<plugin-id>/`.
3. The draft declares permissions, dependencies, tools, tests, and generated artifacts.
4. The plugin page may display the draft as an AI draft.
5. The runtime does not load or register the draft.
6. AI runs available tests or dependency checks and summarizes the result.
7. The user confirms whether the draft should enter a future controlled promotion path, similar to command execution confirmation.

At this stage, that confirmation must not be implemented by modifying `runtime/skills/`, `runtime/api/`, `runtime/app.py`, or built-in tool registration. In-process Python plugin loading remains out of scope until YuntaoCode has a controlled execution boundary.

See [capability-governance.md](capability-governance.md).

## Runtime Loading Flow

This flow is a future implementation target, not current behavior:

1. Discover plugin directories from configured local plugin roots.
2. Parse `plugin.json`.
3. Validate ID, version, permissions, dependencies, and tool IDs.
4. Display permission and dependency status before enabling.
5. Load enabled plugins through a controlled boundary.
6. Register plugin tools in `ToolRegistry`.
7. Execute plugin tools only through Task Runtime tool calls.
8. Write model output, tool calls, confirmations, errors, and generated artifacts into the task trace.

## Open Questions

- Whether external plugins should first run in-process or start with a subprocess boundary.
- How plugin execution should report structured task artifacts.
- How MCP tools map to plugin manifests without duplicating metadata.
- How plugin signing should work after local plugin loading is stable.
