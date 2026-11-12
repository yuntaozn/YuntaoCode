# Security Policy

YuntaoCode is a local-first runtime that can read files, write files, run shell commands, and call local or remote model providers. Security reports are taken seriously because local tool boundaries are part of the core product.

## Supported Versions

The project is currently pre-1.0. Security fixes are applied to the main development branch until formal release branches exist.

## Reporting a Vulnerability

Please do not open a public issue for sensitive vulnerabilities.

Email: wutaoplay@outlook.com

Include:

- A clear description of the vulnerability.
- Steps to reproduce.
- The affected version or commit.
- Impact, especially whether it can escape workspace boundaries, execute commands without confirmation, expose API keys, or leak local user data.

## Security Boundaries

Current intended boundaries:

- Runtime listens on `127.0.0.1` by default.
- File tools are restricted by `PathGuard` to configured workspace roots unless the user enables broader access.
- Write, shell, Git commit, and document export operations require confirmation.
- The optional `runtime.update_task` model protocol only records task semantics
  and plans within one Run. It cannot change access scope or confirmation
  policy, execute external actions, or supply artifact-success evidence.
- API keys and conversation data are stored in the local user configuration directory, not in the project repository.
- User-uploaded attachments are stored in the local Runtime data directory,
  not in project workspaces. Attachment capabilities receive only attachments
  authorized for the current conversation run, and uploads are not executable.
  `attachment.read_image` uses the same conversation-scoped ID allowlist as
  text extraction; it accepts no filesystem path or URL. Historical images are
  read only after an explicit model tool call, with a 10 MiB limit matching
  image uploads. Unsupported media and unauthorized IDs return explicit errors.
- MCP service configuration and secrets are stored separately in the local user
  data directory. Public MCP APIs redact environment and header values.
- MCP service create, update, delete, and lifecycle actions reject browser
  requests whose Origin does not match the local Runtime origin.
- MCP services do not auto-start by default. A service may opt in to
  `lifecycle.auto_start`; auto-start attempts are limited to enabled services
  and are reported as runtime evidence. A package-runner command such as the
  disabled official Blender `uvx --from <versioned-official-source> blender-mcp`
  example may acquire external code only
  after the user explicitly enables that service or opts it into auto-start.
- The default Blender connection explicitly selects the Blender Lab source
  and release tag; the bare PyPI name `blender-mcp` refers to a separate
  third-party project. Existing connections are not silently switched.
- Declared MCP permissions are not enforced as process-level network or
  filesystem isolation. Official Blender code execution has access to Blender's
  Python environment. Code execution and render-to-path tools keep confirmation
  requirements, including when an upstream render tool advertises a read-only
  hint. MCP services remain executable code with their own network behavior.
- MCP stdio JSON lines have a 16 MiB read limit to support inline image results
  while retaining a finite transport buffer.
- Tool image attachments are limited to two images per bridge batch and 2 MiB
  each, except explicit `attachment.read_image` results, which retain the
  existing 10 MiB user-upload limit. Optional pixel inspection rejects images above 16,777,216 pixels before
  loading their pixel buffers. Media is read from the current ToolTask or the
  existing allowed file roots; no new URL fetching or filesystem access is
  granted. Audit records omit binary image data and retain source references.
- Declarative CLI providers are controlled capability providers, not a bypass
  around shell permissions. They must declare command, arguments, timeout,
  permissions, and evidence behavior before they are exposed to tasks.
- AI-built Capability Packs are stored as user-data drafts by default. They do
  not become trusted runtime code, built-in plugins, or executable tool
  adapters without an explicit enablement path, tests, and user confirmation.

Known pre-1.0 hardening work:

- Add consistent API token enforcement.
- Tighten CORS for local API access.
- Formalize plugin permission manifests.
- Add more automated tests for shell and write-tool confirmation flows.
