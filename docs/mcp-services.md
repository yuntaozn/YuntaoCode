# MCP Service Management Boundary

MCP services should have a separate management surface from ordinary plugin
capability groups.

The distinction is operational rather than semantic:

- A plugin or built-in skill provides capabilities and tool contracts.
- An MCP service is an external capability provider with its own process,
  transport, connection state, permissions, dependencies, logs, and lifecycle.
- Tools discovered from an MCP service still enter the normal Task Runtime
  through `ToolRegistry`, confirmations, trace, result audit, and capability
  contracts.

`ToolRegistry` exposes provider origin through a stable provider descriptor:
`provider_kind`, `provider_id`, `source_type`, and `source_id`. The legacy
`source_type/source_id` fields remain for compatibility. The generic MCP
session registers discovered capabilities as `provider_kind=mcp` with the MCP
service configuration ID as `source_id`.

## Why MCP Needs Separate Management

The current plugin page groups registered tools by tool ID prefix. That is
appropriate for showing available capabilities, but it cannot safely manage an
MCP server because an MCP server may require:

- a `stdio`, Streamable HTTP, or legacy SSE transport;
- a command, arguments, working directory, and environment variables;
- secrets that must not be displayed or committed;
- explicit start, stop, reconnect, and health-check actions;
- dependency and version checks;
- per-server permission review;
- logs and connection diagnostics;
- multiple tools whose IDs and schemas are discovered at runtime.

Treating such a server as an imported Python skill hides these operational
facts and couples the core runtime to the external integration.

## Proposed Layers

```text
External Application
  Blender Add-on socket server
        |
MCP Service
  blender-mcp process / transport / lifecycle
        |
MCP Adapter
  discovery / schema normalization / result normalization
        |
Capability Runtime
  capability contract / provider metadata / permission boundary
        |
Task Runtime
  capability routing / confirmation / trace / result audit
```

For Blender specifically:

- Blender Add-on owns the in-application socket server.
- Blender MCP Server owns the MCP protocol and socket bridge.
- YuntaoCode connects to the MCP Server through the generic stdio MCP session.
- Blender-specific tools are not copied into `runtime/skills/`.
- A disabled `blender` example definition is created during the MCP service
  schema migration. It uses the explicit `uvx blender-mcp` package-runner
  command. It does not start automatically by default; users may explicitly
  enable the service and opt in to `lifecycle.auto_start`.
- MCP service source/reference trees live under `mcp-services/<service-id>/`.
  A local source copy, such as `mcp-services/blender-mcp/`, is third-party
  reference material for the MCP service boundary. It is not a built-in Python
  skill, not an automatically loaded plugin, and not required by the default
  `uvx blender-mcp` connection path.
- The Blender example uses conservative per-tool timeouts because the official
  socket bridge can take longer than a normal local tool call, especially for
  viewport screenshots and code execution. These timeouts are operational
  defaults, not success guarantees.

## Runtime Concepts

MCP management keeps four concepts separate even though the current local
configuration stores them together:

- **Server definition**: identity, description, enablement, lifecycle, and
  declared permissions.
- **Connection profile**: stdio command or remote transport details and
  secrets.
- **Session**: the live protocol handshake, negotiated version, server info,
  logs, and connection state.
- **Capability binding**: the mapping from a remote MCP tool name to a
  namespaced `ToolRegistry` ID. Dynamic IDs use an `mcp_<service>.` namespace
  so they cannot collide with built-in providers.

Installation is separate from connection. The Blender example declares
`installation.kind = package_runner`: YuntaoCode does not install or own the
package, and `uvx` may acquire it only after the user explicitly enables the
service and starts it manually or opts in to auto-start.

External application readiness is also separate from MCP connection state.
Service definitions may declare generic `tcp` or `executable` prerequisites.
The Blender example checks both the Add-on socket at `127.0.0.1:9876` and the
availability of `uvx`. A ready Add-on does not mean the MCP protocol session is
connected; it only explains which part of the connection chain is ready.

Capability readiness is advisory by default. If an MCP service is stopped,
protocol-disconnected, or has degraded tool roundtrips, the runtime can still
ground a matching task to that MCP capability and pass the readiness issue to
the model. For enabled services that opted in to `lifecycle.auto_start`, the
runtime may also start the targeted MCP service on demand before the model gets
the final tool snapshot. This keeps the model in charge of strategy while
preventing a missing dynamic tool list from erasing the intended
external-application boundary.

The Blender example also sets `BLENDER_MCP_DISABLE_TELEMETRY=1` by default.
This follows YuntaoCode's local-first boundary, but it is not a substitute for
future process-level network enforcement.

The public service API exposes these views as `server_definition`,
`connection_profile`, `session`, and `capability_bindings` while retaining the
flat configuration fields for pre-1.0 compatibility.

MCP tool annotations are used when available. A service definition may also
declare `tool_policies` for servers that do not publish useful annotations.
The Blender example uses this only to identify known read-only inspection
tools and external-state effects; unknown or state-changing tools continue
through the service permission and confirmation boundary.

Tool policies may declare:

- `risk`: permission and confirmation classification;
- `effects`: observable successful effects such as `external_state_change`;
- `roles`: task roles such as `deliverable`, `evidence`, or `verification`;
- `artifacts`: artifact kinds produced by a successful call.
- `verification_strength`: `weak`, `standard`, or `strong` evidence supplied
  by a successful verification call.
- `call_timeout`: optional per-tool call timeout in seconds. If omitted, the
  service-level `timeouts.call` value is used.

These declarations describe successful result facts, not permission grants.
Failed calls never receive the declared successful effects. Their intended
roles remain available to RunResult so the runtime can distinguish a failed
deliverable, failed verification, and an incidental failure. Each discovered
binding also exposes `health` and `last_error`, so a tool rejected by the
external application can be shown as degraded without disconnecting the whole
MCP service.

## MCP Service Contract Draft

```json
{
  "schema_version": "mcp_service.v1-draft",
  "id": "blender",
  "name": "Blender MCP",
  "enabled": false,
  "transport": {
    "type": "stdio",
    "command": "uvx",
    "args": ["blender-mcp"],
    "cwd": null,
    "env": {}
  },
  "lifecycle": {
    "auto_start": false,
    "restart_policy": "manual"
  },
  "timeouts": {
    "call": 30
  },
  "permissions": {
    "filesystem": "workspace",
    "network": "confirm_each",
    "external_state": "confirm_each",
    "arbitrary_code": "confirm_each"
  }
}
```

Secrets should be stored separately from this public configuration.

## Lifecycle States

The MCP management page should display stable service states:

- `disabled`
- `stopped`
- `starting`
- `running`: a managed stdio process is alive, but no MCP session has completed
  the handshake yet;
- `reachable`: a remote endpoint responded, but no MCP protocol adapter has
  completed the handshake yet;
- `connected`
- `degraded`
- `failed`

Tool availability should follow connection state. A disconnected MCP service
must not leave apparently callable tools in the model context without clear
availability evidence.

Protocol connection and tool roundtrip health are separate. A service can be
`connected` at the MCP protocol layer while one or more discovered tools are
`degraded` because the external application bridge timed out, returned invalid
data, or rejected the operation. In that case YuntaoCode keeps the protocol
state visible, marks the affected bindings with `health` and `last_error`, and
surfaces advisory capability issues to the model. This is not a permission
block; it is runtime evidence that the model should use for strategy selection,
such as restarting the service, running a small smoke test, or choosing another
safe route.

## UI Direction

Keep two distinct views:

- **Plugins / Capabilities**: what capabilities and tools are available to
  tasks, regardless of their implementation source.
- **MCP Services**: how external MCP providers are configured, started,
  connected, diagnosed, and granted permissions.

An MCP-provided capability may appear in the plugin/capability catalog, but
enablement and lifecycle actions belong to the MCP service page.

## Result Contract

MCP tool results must be normalized before entering the Task Runtime:

- failures become real failed tool events, not successful text containing an
  error message;
- generated files expose structured `path`, `artifact_kind`, size, and
  validation facts;
- external application changes expose an explicit external-state-change fact;
- external-state verification may be satisfied by a successful verification
  call that returns structured or state-summary facts after the target state
  change, even if the provider labels the coarse inspection as `weak`;
- visual goals should prefer visual evidence such as screenshot, render, or
  page-capture artifacts. Scene or object metadata is structural evidence and
  should not by itself prove visual quality when the task contract requires
  `visual`;
- failed deliverable or verification attempts remain in the audit trace, but
  a later successful deliverable plus sufficient verification should classify
  them as recovered instead of making the whole run partial;
- tool-call failures update a per-service diagnostic cache. The cache is
  advisory: it helps the next capability snapshot avoid preferring a recently
  degraded tool, but it does not unregister the tool or block the model from
  choosing it when the task evidence supports that route. A later successful
  call clears the diagnostic;
- long-running operations expose progress and cancellation state;
- raw MCP payloads may be retained for audit, but must not replace normalized
  result facts.

## Current Foundation

The runtime now provides an independent MCP service manager and page:

- configurations are stored in the local YuntaoCode data directory;
- `stdio`, Streamable HTTP, and legacy SSE configurations are supported;
- explicit start, stop, restart, endpoint check, state, and recent logs are
  available;
- `check` reports service/process/protocol/prerequisite state without calling
  MCP tools, while `probe` runs a small set of safe no-argument read-only
  evidence/verification tools to confirm end-to-end tool usability;
- enabled services may opt in to `lifecycle.auto_start`, which is attempted
  after Runtime startup and when a task targets the matching MCP capability
  while the service is stopped, on a best-effort basis;
- stdio services perform an MCP initialize handshake, discover tools, call
  tools, and dynamically bind/unbind them in `ToolRegistry`;
- session protocol version, server identity, and capability bindings are
  visible through the service API and management page;
- service pages distinguish protocol connection from tool roundtrip health;
- environment values and HTTP headers are redacted from public API responses;
- MCP-sourced capabilities are visible in the plugin catalog but managed from
  the MCP service page;
- an MCP-sourced tool enters model context only when its service is marked
  protocol-connected.
- discovered tools carry provider-declared effect, role, and artifact facts
  into Task Runtime events, while per-tool call failures update binding health
  and a local diagnostic cache that survives service reconnects;
- provider log messages are length-bounded before entering the local service
  diagnostics view.

Automatic installation, remote marketplaces, and live Streamable HTTP/legacy
SSE protocol sessions remain out of scope. Starting a configured stdio service
is explicit by default; `auto_start` is a per-service lifecycle opt-in, not a
global background plugin loader. It covers both Runtime startup and task-demand
startup.
