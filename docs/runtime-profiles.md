# Runtime Profiles

Runtime profiles define how much of the backend is assembled at startup. They
are not user-facing assistant modes and must not change the Task Runtime
contract. A profile only decides which capability providers, product managers,
and API surfaces are loaded around the same core runtime.

## Profiles

### `full`

`full` is the default product backend. It preserves the current behavior and
loads all built-in tool groups plus the product management surfaces:

- built-in tools: attachment, filesystem, document, spreadsheet, code, shell,
  Git, web, and memory;
- MCP service manager;
- CLI providers;
- automations;
- capability packs and plugin catalog;
- source update checks;
- memory and backup APIs.

### `lite`

`lite` is a foundation profile for testing and future lightweight embedding. It
keeps the Task Runtime usable while leaving product and external-provider
surfaces out of the startup path.

The current lite tool groups are:

- attachment;
- filesystem;
- code;
- shell;
- Git;
- memory.

The current lite profile does not initialize:

- MCP service manager;
- CLI providers;
- automations;
- capability packs;
- plugin catalog routes;
- source update routes;
- document, spreadsheet, or web built-in tools.

## Boundary Rules

- `full` must remain backward-compatible unless a change explicitly migrates
  product behavior.
- `lite` should be kept small enough to explain the foundation: settings,
  workspaces, conversations, runs, tool tasks, attachments, path guard,
  confirmation, trace, and core local tools.
- Adding a new manager or provider should require deciding whether it belongs
  in `full`, `lite`, or both.
- Profiles must not create separate execution semantics. Model calls, tool
  execution, confirmation, RunEvent trace, and RunResult handling should stay
  shared.
- Optional services should be absent from `lite` rather than initialized and
  hidden.

## Startup

```bash
python -m runtime.app --profile full
python -m runtime.app --profile lite
```

The ready event includes the selected profile so desktop shells and tests can
diagnose which backend surface is active.
