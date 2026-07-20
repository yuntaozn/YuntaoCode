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
```

The Harness sits between `ToolCallLoop` and `runtime/model_providers/client.py`.
It is intentionally thinner than a provider client and less powerful than an
agent strategy module.

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
