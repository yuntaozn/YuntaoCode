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
- API keys and conversation data are stored in the local user configuration directory, not in the project repository.
- User-uploaded attachments are stored in the local Runtime data directory,
  not in project workspaces. Attachment capabilities receive only attachments
  authorized for the current conversation run, and uploads are not executable.
- MCP service configuration and secrets are stored separately in the local user
  data directory. Public MCP APIs redact environment and header values.
- MCP service create, update, delete, and lifecycle actions reject browser
  requests whose Origin does not match the local Runtime origin.
- MCP services never auto-start. A package-runner command such as the disabled
  Blender `uvx blender-mcp` example may acquire external code only after the
  user explicitly enables and starts that service.
- Declared MCP network permissions are not yet enforced as process-level
  network isolation. The Blender example disables its supported telemetry by
  default, but third-party MCP services must still be treated as executable
  code with their own network behavior.

Known pre-1.0 hardening work:

- Add consistent API token enforcement.
- Tighten CORS for local API access.
- Formalize plugin permission manifests.
- Add more automated tests for shell and write-tool confirmation flows.
