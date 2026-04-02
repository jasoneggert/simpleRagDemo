from app.ingest import ingest_seed_docs


if __name__ == "__main__":
    result = ingest_seed_docs()
    print(f"Ingested {result['documents']} documents into {result['chunks']} chunks.")
