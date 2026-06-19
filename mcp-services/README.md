# MCP Services

This directory is reserved for MCP service source trees, local reference copies,
and service-specific integration notes.

MCP services are external capability providers. They are not built-in
`runtime.skills.*` modules, and YuntaoCode does not automatically import Python
code from this directory.

Current layout:

- `blender-mcp/`: local reference copy of the Blender MCP service and add-on
  materials. The default YuntaoCode MCP configuration still uses the explicit
  `uvx blender-mcp` package runner. It starts only after the user enables and
  starts the service, or explicitly opts that service in to auto-start.

Use this directory when an integration needs service-specific source,
third-party reference files, or development notes. Runtime-facing service
configuration belongs to the MCP Service Manager, and task-facing capability
contracts still enter through `ToolRegistry`.
