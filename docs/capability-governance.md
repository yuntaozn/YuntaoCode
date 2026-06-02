# Capability Governance

YuntaoCode can read files, write code, run commands, and verify results. This means the model can naturally try to extend the system when a requested capability is missing.

That self-extension ability is useful, but it must be governed.

## Core Rule

Asking whether YuntaoCode can do something is not permission to extend YuntaoCode.

For example:

```text
Can you generate a video?
```

The assistant should answer with the current capability boundary and possible approaches. It should not create a new skill or plugin unless the user explicitly asks for that.

Explicit extension requests include:

```text
Create a video plugin draft for YuntaoCode.
Add a new skill draft for rendering Remotion videos.
Implement this as an AI-built plugin draft.
Extend YuntaoCode with a reusable video capability.
```

## AI-Built Plugin Drafts

AI-built plugins must start as isolated drafts.

Default draft root:

```text
<YuntaoCode data dir>/ai-plugins/
```

Each draft must live in its own directory:

```text
ai-plugins/
  example-plugin/
    plugin.json
    README.md
    src/
    tests/
    artifacts/
```

Deleting one draft directory must not affect built-in runtime code or any other plugin draft.

## Boundaries

AI-built plugin drafts must not modify:

- `runtime/skills/`
- `runtime/api/`
- `runtime/app.py`
- built-in tool registration
- built-in settings defaults

Those files are core runtime code. A draft can reference the extension contract, but it cannot register itself by editing core files.

In the current codebase, confirmation is not permission to edit core runtime files. AI-built drafts must not be imported as `runtime.skills.*` modules, must not be registered by editing `runtime/skills/__init__.py`, and must not execute in-process as trusted Python runtime code.

## Required Draft Contents

Every AI-built plugin draft should include:

- `plugin.json` with ID, name, version, permissions, dependencies, and tool declarations.
- `README.md` explaining purpose, risks, setup, and usage.
- `tests/` or a clear verification script.
- An artifact policy for generated files.
- A rollback note explaining how to remove the draft safely.

## Registration Gate

A draft can be promoted with a lightweight manual confirmation flow:

1. AI finishes the isolated draft.
2. AI runs the available tests or verification script.
3. AI summarizes changed files, permissions, dependencies, and commands.
4. The UI asks for one explicit confirmation, similar to command execution confirmation.
5. After confirmation, the draft can enter a future controlled promotion path.

Until a controlled loader exists, the plugin page may display the draft, but the runtime must not load or execute it as a registered plugin.

## Risk Notice

AI-built plugins can run code, create files, call local tools, or depend on third-party packages. They may contain bugs, unsafe commands, excessive permissions, or unreviewed dependencies.

Users should treat AI-built plugins as generated code, not trusted product features.

## Example Prompt

```text
Please create an AI-built plugin draft for YuntaoCode.
Requirements:
- Write only under the configured ai-plugins/<plugin_id>/ draft directory.
- Do not modify runtime/skills, runtime/api, runtime/app.py, or built-in registration logic.
- Include plugin.json, README.md, minimal source files, tests or verification scripts, permissions, dependencies, and rollback notes.
- Run feasible verification.
- Summarize changed files, permissions, dependencies, and test results.
- Ask me whether to enter the controlled registration or enablement flow.
```
