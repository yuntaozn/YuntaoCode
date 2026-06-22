# CLI Providers

CLI Providers are declarative local command providers for Capability Runtime.
They let YuntaoCode reuse mature command-line tools without turning the Runtime
into free-form shell execution.

## Boundary

```text
Capability
  document.pdf_to_docx

Provider
  cli

Tool
  cli_pdf_tools.convert

Execution
  declared command + declared args + model-filled structured inputs
```

The model does not choose the command string. It only fills the tool input
schema. The Runtime renders the declared arguments, checks path boundaries,
applies confirmation policy, runs the subprocess, evaluates evidence, and
records ToolTask / RunResult facts.

## Provider Shape

```json
{
  "schema_version": "cli_provider.v1",
  "id": "pdf-tools",
  "name": "PDF Tools",
  "enabled": true,
  "tools": [
    {
      "id": "convert",
      "name": "Convert PDF",
      "capability": "document.pdf_to_docx",
      "command": "pdf-to-docx",
      "args": [
        "--input",
        "{input_path}",
        "--output",
        "{output_path}"
      ],
      "input_schema": {
        "type": "object",
        "properties": {
          "input_path": {"type": "string"},
          "output_path": {"type": "string"}
        },
        "required": ["input_path", "output_path"]
      },
      "outputs": [
        {
          "path": "{output_path}",
          "artifact": "docx",
          "required": true
        }
      ],
      "permissions": {
        "filesystem": "workspace",
        "shell": "confirm_each",
        "network": "false",
        "model": "false"
      },
      "timeout": 120,
      "effects": ["file_write"],
      "artifacts": ["docx"],
      "roles": ["deliverable"],
      "verification_strength": "standard",
      "evidence": [
        {"type": "exit_code_zero"},
        {"type": "file_exists", "path": "{output_path}"}
      ]
    }
  ]
}
```

The current implementation stores local provider definitions in:

```text
<YuntaoCode data dir>/cli-providers.json
```

It exposes management APIs:

```text
GET    /cli-providers
POST   /cli-providers
GET    /cli-providers/{provider_id}
PUT    /cli-providers/{provider_id}
DELETE /cli-providers/{provider_id}
```

Mutating requests require a same-origin local Runtime request, matching the MCP
management boundary.

## Evidence

Supported evidence rules in the first implementation:

- `exit_code_zero`
- `file_exists`
- `file_min_size`
- `stdout_contains`
- `stderr_not_contains`

Evidence is returned in the tool output and can be used by RunResult, Runbook,
diagnostics, replay, and future evaluation. A failed required evidence rule
makes the ToolTask fail even if the command exits.

## Why Not Shell

`shell.run_command` is for temporary exploration, tests, and explicit user
commands. A CLI Provider is a reusable capability source:

- command and args are declared before execution;
- model input is limited by `input_schema`;
- paths are resolved through `PathGuard`;
- provider kind is recorded as `cli`;
- effects, artifacts, roles, and verification strength are declared;
- confirmation policy still applies;
- diagnostics can report missing commands or unsupported platforms.

This keeps CLI useful without letting it bypass Capability Runtime.
