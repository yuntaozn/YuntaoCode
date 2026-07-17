# Document Draft Runtime

YuntaoCode now treats long-form document work as a draft state object instead of
a one-shot export prompt.

This is a foundation layer, not a user-facing assistant mode. Paper assistants,
document assistants, report generation, long translation, and manuscript
organization should all be able to reuse the same draft lifecycle.

## Why It Exists

One-shot tools such as `document.export_docx` are useful for short outputs, but
they are a poor fit for long tasks:

- the model has to hold the whole document in one response;
- partial progress is hard to inspect;
- failures make it unclear which parts were actually written;
- later tasks cannot safely resume from a shared document state.

The draft runtime gives the model a simple state object:

```json
{
  "draft_id": "draft_xxx",
  "title": "Report title",
  "sections": [],
  "citations": [],
  "metadata": {}
}
```

The model still decides how to understand the task and how to write. The runtime
only provides storage, append, inspection, export, and audit-friendly metadata.

## Tool Contract

### `document.create_draft`

Creates a persistent draft in the runtime data directory.

Use it when a task is likely to produce a long report, paper, translated
document, manuscript outline, or multi-section deliverable.

An existing `.docx` can be passed as `source_path`. The runtime imports its
text structure into a new draft so later work extends known content instead of
silently starting from an empty document.

### `document.append_draft_section`

Appends content to an existing section, or creates the section if needed.

This is the preferred write path for long-form generation because every append
is visible in task events and the draft can be inspected before export.

The contract requires a complete content block, but does not impose a fixed
block length. The model should choose bounded blocks that fit its current
provider output budget.

### `document.add_draft_citation`

Adds a source/citation record. The runtime does not decide citation style; it
only keeps the source records available to the model and export layer.

### `document.inspect_draft`

Returns section count, block count, citation count, character count, empty
sections, and unknown citation references.

This is an audit and recovery tool. It should help the model and user know what
exists without forcing a workflow.

### `document.export_draft_docx`

Exports the draft to `.docx`.

This is the only draft tool that writes to the workspace. It is protected by
PathGuard, backup, and write confirmation just like other document exports.
The export result includes artifact facts such as path, file size, content
characters, paragraph counts, and draft statistics. These facts let the Task
Runtime audit the produced artifact without adding a scenario-specific
verification branch.

## Boundary

The draft runtime should not become a hard-coded strategy engine.

Allowed:

- store and inspect long-form document state;
- expose clear tool contracts;
- return progress metadata and recoverable facts;
- support final export into workspace files.

Avoid:

- adding special runner branches for "paper", "report", or "translation";
- forcing every document task into the draft runtime;
- encoding writing style, research method, or translation strategy in system
  code;
- treating draft creation as a substitute for final file export.

The runtime should remain small: task state, draft state, traces, inspection,
recovery, and export. The model owns task interpretation.
