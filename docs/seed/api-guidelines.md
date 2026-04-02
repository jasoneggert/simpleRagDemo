# API Guidelines

## Response shape

All JSON API responses should return a stable top-level object. For read flows, prefer
explicit fields over overloaded arrays. For question answering, include the answer, a short
summary, citations, and debug metadata needed during development.

## Error handling

User-facing validation errors should return HTTP 422 with a structured body. Unexpected server
errors should return HTTP 500 and log enough context for debugging, but the UI should receive a
short message instead of a stack trace.

## Observability

During local development, it is useful to show retrieval details such as the selected chunks,
their scores, and a prompt preview. This debug data should not be treated as a stable public API.
