# MCP Services

This directory is reserved for MCP service source trees, local reference copies,
and service-specific integration notes.

MCP services are external capability providers. They are not built-in
`runtime.skills.*` modules, and YuntaoCode does not automatically import Python
code from this directory.

Current layout:

- `blender-mcp/`: legacy third-party Blender MCP service and add-on reference
  material. It is distinct from the official Blender Lab server and is not
  used by the default connection.

The default Blender connection uses the official
[Blender Lab MCP server](https://projects.blender.org/lab/blender_mcp), pinned to
`v1.0.3` through `uvx --from`. It starts only after the user enables and starts
the service, or explicitly opts that service in to auto-start. See
[the connection and migration guide](../docs/mcp-services.md).

Use this directory when an integration needs service-specific source,
third-party reference files, or development notes. Runtime-facing service
configuration belongs to the MCP Service Manager, and task-facing capability
contracts still enter through `ToolRegistry`.
