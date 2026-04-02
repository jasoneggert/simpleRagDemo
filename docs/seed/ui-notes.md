# UI Notes

## Developer experience

The demo UI should let a user ask a question, inspect the generated answer, and expand supporting
details. Showing the retrieved chunks and prompt preview makes it easier to understand why a RAG
response was generated.

## Citations

Citations should be easy to scan. Each citation should include the source title, source path, and
a short quote from the supporting chunk. The UI can render citations as cards or a compact list.

## Loading states

While a request is in flight, disable duplicate submits and show a visible loading state. If the
backend returns validation or network errors, surface them inline near the question form.
