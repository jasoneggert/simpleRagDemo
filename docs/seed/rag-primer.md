# RAG Primer

## Retrieval

Retrieval-augmented generation works by grounding the model on external content before generation.
A typical flow is: chunk the source documents, generate embeddings for each chunk, store them in a
vector database, embed the user query, retrieve the nearest chunks, and inject those chunks into
the prompt.

## Prompting

The prompt should clearly separate instructions, retrieved context, and the user question. It
should also specify how to behave when the answer is uncertain. Good prompts ask the model to cite
the supporting chunks and avoid inventing facts that are not present in retrieved context.

## Structured output

When the model returns JSON, validate it before sending it to the frontend. Validation catches
schema drift and makes the UI simpler because it can render a predictable shape.
