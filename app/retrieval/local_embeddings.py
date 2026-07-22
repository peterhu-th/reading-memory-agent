import hashlib
import math
import re

from langchain_core.embeddings import Embeddings


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


class LocalHashEmbeddings(Embeddings):
    """Small deterministic embedding function for local MVP indexing.

    This avoids depending on a remote /embeddings endpoint. It is good enough
    for smoke-testing the RAG pipeline, but can be replaced with a real embedding
    model later.
    """

    def __init__(self, dimensions: int = 512) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be greater than 0")
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = self._tokens(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _tokens(self, text: str) -> list[str]:
        base_tokens = [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]
        char_bigrams = [
            text[index : index + 2]
            for index in range(max(0, len(text) - 1))
            if not text[index : index + 2].isspace()
        ]
        return base_tokens + char_bigrams
