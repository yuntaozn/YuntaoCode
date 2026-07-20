# Desktop Observation Provider

`providers/desktop_observation/` is an incubating local provider for read-only
desktop observation.  It is intentionally kept outside `runtime/` so it can
later become a standalone package or service without carrying YuntaoCode's
Task Runtime internals with it.

## Position

The provider answers a narrow question:

```text
What is observable on this local desktop right now?
```

It does not answer:

```text
What should the model do next?
Should the task be considered complete?
Should the computer be controlled automatically?
```

Those decisions remain with the model and YuntaoCode Runtime.  Desktop
Observation only returns facts.

## Current Scope

Current tools exposed through the YuntaoCode adapter:

- `desktop.list_windows`
- `desktop.active_window`
- `desktop.list_processes`
- `desktop.capture_screen`
- `desktop.capture_window`

The first three produce `desktop_state.v1`.  The screenshot tools also produce
`visual_evidence.v1` and write image artifacts into the task temporary
directory by default.

## Non-Goals

The provider must not add desktop control in this phase:

- no click
- no type
- no hotkey
- no focus switch
- no move or resize window
- no close window
- no kill process

If active control is added later, it should be a separate capability with a
separate permission and confirmation model.

## Contracts

`desktop_state.v1` is a cross-agent observation record:

```json
{
  "schema_version": "desktop_state.v1",
  "kind": "desktop_state",
  "source": "desktop_observation",
  "platform": "Windows",
  "scope": "windows",
  "captured_at": "2026-07-20T00:00:00Z",
  "counts": {
    "windows": 1,
    "processes": 0,
    "diagnostics": 0
  },
  "active_window": {},
  "windows": [],
  "processes": [],
  "diagnostics": []
}
```

Screenshots use the shared `visual_evidence.v1` shape so they can enter
RunResult, RunEvidence, model visual context, diagnostics, and future replay
fixtures.

## Independence Boundary

The provider package should avoid importing `runtime.*`.  The YuntaoCode
adapter in `runtime/skills/desktop.py` is responsible for:

- registering `ToolSpec` metadata,
- resolving task temporary output paths,
- applying workspace/path guard rules for explicit output paths,
- mapping provider records into Capability Runtime artifacts, effects, roles,
  and verification strength.

This boundary allows future exports:

```text
providers/desktop_observation
  -> Python package
  -> CLI command
  -> HTTP local service
  -> MCP service
```

without rewriting the observation core.

## Platform Strategy

Windows window enumeration is implemented first because current testing is
mostly on Windows.  macOS and Linux should degrade with structured diagnostics
until platform adapters are implemented.

Future platform adapters should keep the same contracts:

- Windows: Win32 APIs plus Pillow ImageGrab.
- macOS: Accessibility/ScreenCaptureKit or a local helper.
- Linux: X11/Wayland-specific adapters with clear capability diagnostics.

Missing platform permissions should degrade only this provider, not the whole
Runtime.

## Security And Privacy

Desktop observation is local-only but privacy-sensitive.  A screenshot can
capture chats, browser pages, local files, credentials, and private data.

Therefore:

- screenshot tools require confirmation;
- image artifacts default to the task temporary directory;
- explicit output paths must pass PathGuard;
- records should be used as evidence, not as hidden task-routing rules;
- diagnostics should explain missing platform permission or dependency issues.

## Relationship To YuntaoCode

YuntaoCode consumes Desktop Observation as a Capability Provider:

```text
desktop.observation
  provider_kind=desktop
  lifecycle=local_observer
  artifacts=desktop_state / screenshot / visual_evidence
  roles=evidence / verification
```

This keeps it aligned with MCP, CLI, builtin tools, and future plugin
providers while still allowing independent incubation.

