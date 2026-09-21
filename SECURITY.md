# Security

## Reporting a vulnerability

Please report security problems privately through the repository's "Report a vulnerability" option under the Security tab, not in a public issue. Include the version, what you did, and what happened. Expect an acknowledgement within a few days.

## Threat model

SpecGuard reads files that other people or programs wrote, and specifications that may come from an AI agent. It treats both as untrusted.

| Risk | What SpecGuard does |
| --- | --- |
| Malicious YAML | Safe loader only; anchors and aliases refused (no alias expansion attacks); 1 MB limit. |
| Catastrophic regular expressions | Patterns are length-limited, must not match the empty string, and run under a 2-second timeout. |
| Huge files | Documents over 25 MB and baseline files over 5 MB are refused. |
| Malicious or malformed DOCX | Opened read-only through python-docx. The archive is checked first: it must be a ZIP with `word/document.xml`, at most 5,000 entries, and at most 250 MB uncompressed. Failures produce a short error. |
| Path traversal | The MCP server only reads inside the folders given with `--root`; `..` and symlink escapes are refused after resolving. `baseline_file` may not point outside the specification's folder. |
| Encoding tricks | Text is decoded as UTF-8 (BOM handled), UTF-16 with BOM, or Windows-1252 with a notice; binary data is rejected. |
| Information leaks | Errors carry a short message, not a traceback or internal path detail. `SPECGUARD_DEBUG=1` restores tracebacks locally. |
| Code execution | Nothing in an audited document is executed. SpecGuard runs no subprocesses. |

## Privacy

SpecGuard makes no network requests and sends no document text anywhere. The MCP HTTP transport, if you start it, listens on `127.0.0.1` unless you pass `--host`. If you expose it to other machines, add your own authentication in front of it: it can read any file under its `--root` folders.

A `SemanticVerifier` you plug in yourself may send text to a service; that is your decision and your responsibility.

## Known limits

- The regular expression timeout bounds the time of a single match, not the total across a very large document.
- Dependencies (python-docx, lxml, PyYAML, mcp) carry their own risks. Keep them updated.
