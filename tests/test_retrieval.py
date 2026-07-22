def test_vector_retriever_importable():
    from app.retrieval.vector_retriever import VectorRetriever

    assert VectorRetriever is not None


def test_local_hash_embeddings_are_deterministic():
    from app.retrieval.local_embeddings import LocalHashEmbeddings

    embeddings = LocalHashEmbeddings(dimensions=32)
    assert embeddings.embed_query("孤独") == embeddings.embed_query("孤独")
    assert len(embeddings.embed_query("孤独")) == 32
