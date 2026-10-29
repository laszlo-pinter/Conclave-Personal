# Release Notes: v0.5.1

Conclave v0.5.1 adds a viewer for workspace files to the web UI.

## Upgrading

```bash
pip install --upgrade "conclave-personal[mcp]"
```

Restart the Conclave server and reload the web UI. No database changes, no
API changes.

## New: file viewer in the Files area

- A click on a file in the Files area opens it below the file list, with its
  name, size and a close button.
- Markdown files (`.md`, `.markdown`) are shown formatted, with a toggle
  between the formatted view and the source. Other text files are shown as
  text with syntax highlighting.
- "Insert into chat" adds `@workspace/<path>` to the message input, as a click
  on a file did before. In the chat sidebar, a click still inserts the
  reference directly.
- The viewer is read only. Files that are too large, binary, missing or hidden
  show the server's message instead.

## Security

Markdown in workspace files is treated like model output: it is rendered with
`marked` and filtered with DOMPurify, under the same Content-Security-Policy.
Embedded scripts, event handlers and `javascript:` links have no effect; a
browser test checks this.

## Verification

- `python -m pytest`, including browser tests for the viewer (formatted and
  source view, embedded attacks without effect, text files, insert, errors)
- Full suite also with `CONCLAVE_API_KEY` set, as in CI

v0.5.1 remains alpha.
