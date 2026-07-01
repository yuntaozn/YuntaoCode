# Document Encoding

YuntaoCode documentation is stored as UTF-8 text without BOM.

This matters because several contributors and AI agents work from Windows,
macOS, Linux, PowerShell, terminals, editors, and web UIs. If a tool reads a
UTF-8 Chinese document with the wrong default encoding, the file can appear as
mojibake even when the file itself is valid.

## Rules

- Store Markdown and text documentation as UTF-8 without BOM.
- Prefer editors that respect `.editorconfig`.
- When reading documentation from PowerShell, pass `-Encoding UTF8`:

```powershell
Get-Content docs\context-runtime.md -Encoding UTF8
```

- Do not rewrite a document just because one terminal displays mojibake. First
  verify with the encoding check:

```bash
python scripts/check_doc_encoding.py
```

- Do not mix encodings in one file.
- Do not paste text through tools that silently convert UTF-8 to a system
  code page.

## Check Scope

`scripts/check_doc_encoding.py` checks public documentation files for:

- invalid UTF-8 bytes;
- UTF-8 BOM;
- common mojibake markers such as replacement characters or UTF-8/GBK
  mis-decoding fragments.

The script is a documentation hygiene check only. It does not validate
architecture content, terminology, or writing style.
