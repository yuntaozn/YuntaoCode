# Runtime Extension Contract Draft

This document defines the early plugin direction for YuntaoCode as a Task Runtime extension contract.

The current release has a **Capabilities & Plugins** page. It groups built-in
tools by tool ID prefix, such as `filesystem`, `code`, `shell`, `git`, and
`web`, and may also show MCP-discovered capabilities, local Capability Packs,
and legacy AI-built plugin drafts. These entries are capability provider views,
not all third-party plugins. External plugin loading, remote indexes,
auto-update, and marketplace distribution are intentionally out of scope until
the Task Runtime contract is stable.

A plugin is a versioned, distributable package. It may contain model-facing
skills, Capability Packs, MCP or CLI provider descriptors, external provider
adapters, hooks, and static assets. A package is not itself an execution engine:
task state, provider lifecycle, permission checks, plan execution, trace,
recovery, verification, and audit remain Runtime concerns.

In the runtime architecture, executable plugin components become providers of
Capability Contracts. Non-executable components remain method or context
assets. The model may propose using either kind, but the Runtime owns context
selection and validates capability IDs, tool IDs, permissions, confirmations,
and artifacts before execution. See
[capability-runtime.md](capability-runtime.md) and
[capability-router.md](capability-router.md).

## Current Boundary

- Built-in capabilities are registered from `runtime/skills/`.
- The current `/plugins` API displays capability provider groups and their dependency status.
- Runtime-owned context capabilities such as `attachment` and `memory` are read-only in the capability page and are managed by their own runtime settings.
- Built-in foundation capabilities such as `filesystem`, `code`, `shell`, and `git` may be enabled or disabled from the capability page, but hard guards still apply.
- Built-in optional capabilities such as `document` and `web` may be enabled or disabled, and dependency or network boundaries should remain visible.
- `runtime/core/plugin_manifest.py` defines the pure `plugin_manifest.v1` and
  `plugin_installation.v1` contract skeletons. Discovery, installation, loading,
  and execution are not implemented.
- Contract examples are documented in this file only; the repository does not ship external plugin sample directories at this stage.
- Local Capability Packs belong under the local data directory
  `capability-packs/` and are displayed as pack assets only.
- AI-built executable drafts are not Python skill modules. They must not be
  imported through `runtime.skills.*` or registered by editing
  `runtime/skills/__init__.py`.

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

## Package, Provider, And Local State

Three independent concepts must not collapse into one record:

```text
Plugin Manifest
  Package-owned identity, version, components, requested permissions, and
  compatibility declarations.

Plugin Installation
  Runtime-owned source, installed path, content digest, review state, and
  discovered/installed/quarantined/removed state plus independently enabled
  components.

Capability Provider
  Executable capability source registered through Capability Runtime, such as
  builtin, CLI, MCP, or a future isolated external provider.
```

A package cannot declare itself reviewed, trusted, or enabled. Installing a
package does not enable it, reviewing it does not bypass permissions, and
enabling one component does not grant unrestricted access to the others.

## Not Every Extension Is A Plugin

YuntaoCode should keep these layers separate:

```text
Capability Provider
  Supplies executable tools or external state access.

Skill Pack
  Supplies reusable task method, prompt guidance, or behavior rules.

MCP Service
  Supplies remote or local MCP tools with its own lifecycle.

Runtime Feature
  Supplies core task, context, memory, attachment, run, or recovery behavior.
```

A prompt-methodology asset similar to a `SKILL.md` should not be registered as
an executable provider only because it influences model behavior. Locally
learned methods belong in a Capability Pack, usually with
`kind: method_skill`. When such an asset needs versioned distribution, it may
be one component inside a plugin package without becoming executable code.

## Contract Shape

Local evolution assets and distributable packages use separate roots:

```text
<YuntaoCode data dir>/capability-packs/
  items/

<YuntaoCode data dir>/plugins/
  installed/
  cache/
  installations.json
```

Only the first root exists in the current implementation. The plugin root is a
future storage boundary documented here so package installation is not later
mixed into Capability Pack evolution data.

Local Capability Packs should live under a user-controlled local data directory:

```text
<YuntaoCode data dir>/capability-packs/
  items/
    example-method/
      SKILL.md
      examples/
    example-tool-adapter/
      plugin.json
      README.md
      src/
      tests/
```

Legacy `ai-plugins/` draft scanning may remain for compatibility, but new
AI-created capabilities should use Capability Packs. A Capability Pack may
later be exported into a plugin package; it should not be born in the installed
plugin directory.

## Pack Manifest

The current user-data-level schema is `capability_pack.v1`. See
[capability-packs.md](capability-packs.md).

The preferred default is a method skill:

```json
{
  "schema_version": "capability_pack.v1",
  "id": "long-document-method",
  "name": "Long Document Method",
  "kind": "method_skill",
  "state": "draft",
  "entry": {
    "kind": "instructions",
    "main": "SKILL.md"
  },
  "permissions": {
    "filesystem": "none",
    "shell": "false",
    "network": "false",
    "model": "false"
  }
}
```

Only when a new executable provider is truly needed should a pack become a
`tool_adapter` draft:

```text
<YuntaoCode data dir>/capability-packs/items/example-tool-adapter/
    capability.json
    README.md
    src/
    tests/
```

## Plugin Package Manifest

The pure schema skeleton is `plugin_manifest.v1`:

```json
{
  "schema_version": "plugin_manifest.v1",
  "id": "document-workflows",
  "name": "Document Workflows",
  "version": "0.1.0",
  "description": "Reusable document methods with an optional provider.",
  "components": [
    {
      "kind": "skill",
      "id": "document-review",
      "path": "skills/document-review/SKILL.md"
    },
    {
      "kind": "mcp_provider",
      "id": "office-service",
      "path": "providers/office.mcp.json",
      "optional": true
    }
  ],
  "requested_permissions": {
    "filesystem": "workspace",
    "shell": "false",
    "network": "confirm_each",
    "model": "false"
  },
  "external_apps": [],
  "compatibility": {
    "min_runtime_version": "0.1.0",
    "platforms": ["windows", "linux", "macos"]
  }
}
```

Component paths must be portable relative paths and must not escape the package
root. Supported contract kinds are currently `skill`, `capability_pack`,
`mcp_provider`, `cli_provider`, `external_provider`, `hook`, and `asset`.
Support in the schema does not mean the current Runtime loads that kind.

Local installation state is stored separately as `plugin_installation.v1` and
records source, digest, install state, review state, and enabled component IDs.
These fields must never be accepted from the package manifest as authority.

## Tool Adapter Draft Manifest

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

AI can create Capability Pack drafts, but the draft must stay isolated:

1. The user explicitly asks for a new skill, reusable capability, plugin, or
   tool adapter.
2. AI creates a draft under
   `<YuntaoCode data dir>/capability-packs/items/<pack-id>/`.
3. AI starts with `kind: method_skill` unless the request truly needs a new
   executable provider.
4. A `tool_adapter` draft declares permissions, dependencies, tools, tests,
   and generated artifacts.
5. The capability page may display the pack as a local Capability Pack.
6. The runtime does not load or register executable draft code.
7. AI runs available tests or dependency checks and summarizes the result.
8. The user confirms whether the draft should enter a future controlled promotion path, similar to command execution confirmation.

At this stage, that confirmation must not be implemented by modifying `runtime/skills/`, `runtime/api/`, `runtime/app.py`, or built-in tool registration. In-process Python plugin loading remains out of scope until YuntaoCode has a controlled execution boundary.

See [capability-governance.md](capability-governance.md).

## Skill Evolution Boundary

Capability Packs and Skill Evolution are related but separate.

- A `method_skill` pack describes reusable model-facing task method.
- A `tool_adapter` pack describes a possible executable capability provider.
- A Skill Candidate describes a reusable task pattern backed by Runbook
  evidence.
- Replay Fixtures and Skill Replay Results test whether the candidate works
  against historical task samples.
- Skill Promotion is a manual enablement decision after replay evidence exists.

Therefore an AI-built Capability Pack should not become trusted runtime code
only because the user confirmed that the draft was created. It can become one
candidate artifact in the Skill Evolution flow, but executable registration or
enablement still requires a controlled boundary. See
[skill-evolution.md](skill-evolution.md).

## Future Runtime Loading Flow

This flow is a future implementation target, not current behavior:

1. Discover a configured package source or explicit local package.
2. Parse and validate `plugin_manifest.v1`, including relative component paths.
3. Copy immutable package content into a versioned cache and compute its digest.
4. Create a Runtime-owned `plugin_installation.v1` record in `unreviewed` state.
5. Display components, requested permissions, compatibility, source, and digest.
6. Review and enable components independently where their provider lifecycle permits it.
7. Register executable components only through Capability Runtime and an
   isolated provider boundary; skills and packs enter their own selection path.
8. Execute provider tools only through normal Task Runtime tool calls.
9. Write model output, tool calls, confirmations, errors, and generated artifacts into the task trace.

For an early catalog, a reviewed JSON index hosted on GitHub, Gitee, or a local
file is sufficient. A dedicated marketplace server is not required until
publishing, identity, moderation, signing, or team policy creates a real server
requirement.

## MCP Boundary

MCP services are external capability providers, but their process, transport,
connection, permission, and lifecycle management should not be folded into the
ordinary plugin capability list. See [mcp-services.md](mcp-services.md).

Connected MCP tools may appear in the capability page as a read-only capability
group. That entry is a live capability view, not an installed plugin and not a
second lifecycle control surface.

## Open Questions

- Which isolated subprocess or service boundary external providers should use;
  in-process third-party loading is not the preferred default.
- How plugin execution should report structured task artifacts.
- How plugin signing should work after local plugin loading is stable.
