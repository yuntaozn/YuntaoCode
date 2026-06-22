# Capability Governance

YuntaoCode can read files, write code, run commands, call MCP services, and
verify results. This means the model can naturally try to extend the system
when a requested capability is missing.

That self-extension ability is useful, but it must be governed.

## Core Rule

Asking whether YuntaoCode can do something is not permission to extend
YuntaoCode.

For example:

```text
Can you generate a video?
```

The assistant should answer with the current capability boundary and possible
approaches. It should not create a new skill, Capability Pack, plugin, or tool
adapter unless the user explicitly asks for that.

Explicit extension requests include:

```text
Create a reusable method skill for long document translation.
Summarize this successful task into a Capability Pack.
Create a tool adapter draft for rendering Remotion videos.
Extend YuntaoCode with a reusable video capability.
```

## Default Path: Method Skill Pack

Most AI-created capabilities should start as `method_skill` Capability Packs,
not executable plugins.

A method skill can contain:

- `SKILL.md`;
- task framing prompts;
- step-by-step procedures;
- tool route preferences;
- counterexamples and failure modes;
- verification checklists;
- examples from successful or failed tasks.

This is the easiest and safest way for YuntaoCode to learn from real use. It is
portable across projects, exportable to another machine, and does not require
generated code to run inside the trusted runtime.

Default root:

```text
<YuntaoCode data dir>/capability-packs/items/<pack-id>/
```

## Tool Adapter Drafts

Create a `tool_adapter` pack only when the user explicitly wants a new
executable capability or when a method skill cannot solve the missing boundary.

Tool adapters can run code, create files, call local tools, or depend on
third-party packages. They may contain bugs, unsafe commands, excessive
permissions, or unreviewed dependencies.

Users should treat tool adapter packs as generated code, not trusted product
features.

## Boundaries

AI-built Capability Packs must not modify:

- `runtime/skills/`;
- `runtime/api/`;
- `runtime/app.py`;
- built-in tool registration;
- built-in settings defaults.

Those files are core runtime code. A pack can reference extension contracts,
but it cannot register itself by editing core files.

In the current codebase, confirmation is not permission to edit core runtime
files. AI-built packs must not be imported as `runtime.skills.*` modules, must
not be registered by editing `runtime/skills/__init__.py`, and must not execute
in-process as trusted Python runtime code.

## Project Workspace Rule

AI-built capability drafts must not be written into the current project
workspace, including:

```text
<workspace>/ai-plugins/
<workspace>/capability-packs/
```

The workspace might be an open-source repository. Writing generated capability
assets there creates accidental commit risk and pollutes the project
development rhythm.

Use the user data directory instead:

```text
<YuntaoCode data dir>/capability-packs/items/<pack-id>/
```

## Required Pack Contents

Every method skill pack should include:

- `SKILL.md` with purpose, scope, steps, and verification checklist;
- examples or notes when available;
- known failure modes;
- source/provenance metadata when created from a Run.

Every tool adapter pack should additionally include:

- manifest information with ID, name, version, permissions, dependencies, and
  tool declarations;
- `README.md` explaining setup, risks, and usage;
- `tests/` or a clear verification script;
- an artifact policy for generated files;
- a rollback note explaining how to remove the draft safely.

## Registration Gate

A pack can be reviewed with a lightweight manual confirmation flow:

1. AI finishes the isolated pack.
2. AI runs available checks or verification scripts.
3. AI summarizes files, permissions, dependencies, and test results.
4. The UI asks for explicit confirmation if the pack should be enabled or
   promoted.
5. Method skills may become selectable context assets.
6. Tool adapters remain non-executable until a controlled execution boundary
   exists.

Until a controlled loader exists, the capability page may display the pack, but
the runtime must not load or execute tool adapter code as a registered plugin.

## Example Prompt

```text
Please create a method-skill Capability Pack for YuntaoCode from this task.
Requirements:
- Write only under the configured capability-packs/items/<pack-id>/ draft directory.
- Do not modify runtime/skills, runtime/api, runtime/app.py, or built-in registration logic.
- Include SKILL.md, applicable scenarios, steps, verification checklist, counterexamples, and known failure modes.
- Include provenance metadata if the source Run or task is available.
- If you believe a tool adapter is required, explain why before creating executable code.
```
