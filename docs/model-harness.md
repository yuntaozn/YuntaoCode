# Model Harness

`runtime/model_harness.py` is the model-transport adaptation boundary for
YuntaoCode.  It borrows the useful part of the Harness idea without turning it
into a second planner.

## Position

The Harness answers:

```text
How should this model round be represented for the selected provider?
```

It does not answer:

```text
What is the user's task?
Which tool should be used?
Is the task complete?
Should verification continue?
```

Those decisions remain with the model and Task Runtime evidence loop.

## Current Responsibilities

- Inspect model/provider transport facts such as provider id, wire API,
  streaming support, tool support, vision support, and thinking mode.
- Build a `ModelRoundRequest` with the provider-facing request shape used by
  `ToolCallLoop`.
- Detect visual-input transport errors as transport facts.
- Downgrade rejected image input into text evidence that preserves artifact
  paths, dimensions, console/page errors, and other available facts.

## Non-Goals

The Harness must not:

- infer user intent;
- select a profile, tool, provider, or route;
- rank capabilities;
- decide whether to stop, retry, or mark a Run complete;
- hide failed evidence from RunResult or Task Trace.

If a model-specific rule starts choosing task strategy, it belongs in the model
message as an advisory fact or in the model's own reasoning, not in the
Harness.

## Relationship To Existing Layers

```text
Conversation Runner
  orchestrates the Run lifecycle.

ToolCallLoop
  streams one model round and records transport facts.

Model Harness
  shapes provider-facing model requests and normalizes transport-level
  fallbacks.

Model Provider Client
  performs HTTP/SSE requests, request budgeting, response parsing, and provider
  error formatting.

Model Call Lifecycle
  records purpose, elapsed time, heartbeat, timeout, cancellation, and outcome
  for auxiliary non-streaming requests.
```

The Harness sits between `ToolCallLoop` and `runtime/model_providers/client.py`.
It is intentionally thinner than a provider client and less powerful than an
agent strategy module.

## Streaming Lifetime And Errors

Streaming HTTP requests retain a 20-second connection timeout and the existing
idle watchdog, whose default effective limit is 240 seconds. Active streams
have no fixed total-duration cutoff. Idle time is measured from received bytes,
including SSE keepalives and incomplete frames, rather than parsed model deltas.
The diagnostic reports the measured idle duration and effective limit without
recommending a next action. Run round limits and user cancellation still apply.
Non-streaming calls keep their separate request timeout.

The background fetch forwards every request exception as an error event before
its end signal, including Tornado `HTTPClientError` and `HTTPTimeoutError`.
HTTP status codes and original error text remain available. Previously, a
300-second request timeout could escape the `OSError` handler and be discarded
during cleanup, leaving only a missing-answer result. Worker failures now reach
normal RunResult/checkpoint finalization; received text and reasoning survive.
Cancellation remains cancellation and cleans up the producer rather than
becoming a provider error.

`ToolCallLoop` records `missing_tool_call_payload` when a completed stream ends
with `tool_calls` or `function_call` but contains no named structured call.
`ToolCallLoop` first recovers only a fully framed body using the model/provider's
explicit `text_tool_protocol` setting (`function_call`, `tagged`, or `xml`). The
default is `none`; reasoning and prose examples never become calls. The runner
returns protocol facts to the main model within the normal Run resource budget,
without a separate semantic retry gate. This check does not infer task intent
or select the next tool.
The observation alone cannot establish whether a provider omitted the payload
or an adapter lost it.

Structured call indices must be integers in `[0, 128)`. Invalid chunk shapes,
field types, indices, or a batch containing unnamed calls invalidate the whole
round's call batch, including previously accumulated calls. The provider adapter
retains malformed entries for this validation instead of silently dropping them.
`invalid_tool_call_index`, `invalid_tool_call_chunk`, and
`incomplete_tool_call_batch` use the same factual feedback boundary. A bad
round cannot fall back to text-call recovery or execute a valid subset. Streaming
usage, finish reason, and the final round audit remain available.

Every round emits a durable `model_round.v1` summary: round index, finish reason,
usage, elapsed time, text lengths, requested tool count, normalized call counts,
wire call item counts when observed, call source, interruption, and protocol
errors. Wire item counts count payload fragments, not unique calls. Prompts,
arguments, response text, and reasoning text are excluded. These records allow
diagnostics to compare the provider payload shape with normalized calls without
promoting transport facts into task decisions.

## Future Extension

Future harness variants may adapt:

- OpenAI-compatible chat completions;
- OpenAI Responses-style input;
- Claude-style tool call messages;
- local llama.cpp quirks;
- model-specific multimodal payloads;
- provider-specific reasoning/thinking fields.

Each variant should keep the same rule: transport adaptation only, no hidden
task routing.

## Auxiliary Non-Streaming Calls

`runtime/model_calls.py` is adjacent to the Harness but has a different job.
Task-contract interpretation and final result synthesis use non-streaming
model requests. Their lifecycle is now observable
through `model_call.v1` events and live heartbeats.

The lifecycle layer may bound a request and report transport failure, but it
does not interpret the answer. Each caller remains responsible for its existing
optional fallback. A timeout is therefore a provider/lifecycle fact, not a
runtime verdict that the user task failed.

## Image Transport Receipts

`ToolCallLoop` records `visual_context_delivery` in each model-round audit using
image content fingerprints. A response to a request containing images records
`accepted`; empty or interrupted streams remain `unconfirmed`. Image rejection
followed by text fallback records `omitted_transport_fallback`. This is a
transport receipt, not evidence that the model inspected or approved the image.
MCP inline images use the same existing user-image content shape for Chat
Completions and Responses; no tool-selection or completion policy is added.
