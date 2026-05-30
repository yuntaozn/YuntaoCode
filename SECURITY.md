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

Known pre-1.0 hardening work:

- Add consistent API token enforcement.
- Tighten CORS for local API access.
- Formalize plugin permission manifests.
- Add more automated tests for shell and write-tool confirmation flows.
