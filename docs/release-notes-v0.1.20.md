# Release Notes: v0.1.20

Conclave v0.1.20 adds live response delivery for parallel orchestration in the
desktop UI.

## Highlights

- Parallel orchestration now uses a streaming API endpoint so agent answers can
  be shown as soon as each participant finishes.
- The desktop UI creates pending message rows immediately, updates each row
  when the matching answer arrives, and keeps the existing final refresh.
- Parallel runs now send all selected agents as one group instead of converting
  them into sequential single-agent groups.
- `POST /conversations/<conversation_id>/orchestrate-parallel-stream` exposes
  the event stream for local clients.
- OpenAPI output and API reference documentation include the new streaming
  endpoint.

## Behavior

The non-streaming `POST /conversations/<conversation_id>/orchestrate-parallel`
endpoint remains available. The new desktop path is optimized for feedback
during a running orchestration: users can see that all agents have started and
then read each answer as it is persisted.

Responses are stored in completion order. Conclave still does not verify the
truth of model answers. The human decides. Always.

## Verification

The v0.1.20 release surface was verified locally with:

- `python -m pytest`
- CLI handler streaming tests
- API streaming endpoint tests
- OpenAPI contract tests
- UI surface tests

v0.1.20 remains alpha.
