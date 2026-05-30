# Plugin System Draft

This document captures the intended v0.2 direction for third-party plugins. The current release groups built-in tools by ID prefix and supports enable/disable controls, but it does not yet dynamically load external plugins.

## Goals

- Let third-party plugins declare tools without editing `runtime/skills/__init__.py`.
- Make permissions visible before a plugin can run.
- Keep local file, shell, network, and model access explicit.
- Let dependency problems degrade one plugin instead of breaking the runtime.
- Preserve a stable tool protocol for MCP and future marketplace work.

## Non-Goals for v0.2

- Remote plugin marketplace.
- Background auto-update.
- Running untrusted code without user review.
- Enterprise policy distribution.

## Proposed Directory Shape

```text
plugins/
  example-plugin/
    plugin.json
    plugin.py
    README.md
```

## Proposed Manifest

```json
{
  "id": "example",
  "name": "Example Plugin",
  "version": "0.1.0",
  "description": "Adds example local tools.",
  "entrypoint": "plugin.py",
  "permissions": {
    "filesystem": "workspace",
    "shell": false,
    "network": false,
    "model": false
  },
  "dependencies": {
    "python": [">=3.10"],
    "packages": []
  },
  "tools": [
    {
      "id": "example.echo",
      "name": "Echo",
      "description": "Echo input text.",
      "requires_confirmation": false,
      "local_only": true
    }
  ]
}
```

## Runtime Loading Flow

1. Discover plugin directories from configured plugin roots.
2. Parse `plugin.json`.
3. Validate ID, version, permissions, dependencies, and tool IDs.
4. Load enabled plugins.
5. Register each tool in `ToolRegistry`.
6. Surface dependency and permission status in `/plugins`.

## Permission Model

Initial permission levels should be intentionally small:

- `filesystem`: `none`, `workspace`, or `full_local`.
- `shell`: `false`, `confirm_each`, or `allow`.
- `network`: `false`, `confirm_each`, or `allow`.
- `model`: `false`, `confirm_each`, or `allow`.

Write tools, shell tools, Git commit tools, and export tools should keep confirmation even when the plugin is enabled.

## Open Questions

- Whether plugins should run in-process first or start with a subprocess boundary.
- How plugin signing should work before marketplace distribution.
- How MCP tools map to plugin manifests without duplicating metadata.
