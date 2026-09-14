"""ChromaDB vector store wrapper — semantic memory for the learner.

Provides embedded, persistent semantic search over four collections that back
the agents' cross-session memory:

- ``vocabulary``      — words + definitions + example sentences
- ``grammar_rules``   — rule explanations + examples
- ``conversations``   — past conversation turns with context
- ``cultural_notes``  — cultural insights and when to apply them

Embeddings default to ChromaDB's bundled model. The design targets a
multilingual model (``multilingual-e5-small``); the embedding function is
injectable so the model can be swapped without touching call sites, and tests
can supply a fast deterministic stub.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import settings

COLLECTIONS = ("vocabulary", "grammar_rules", "conversations", "cultural_notes")


def _chroma_path() -> Path:
    path = Path(settings.chroma_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


class VectorStore:
    """Thin wrapper over a persistent ChromaDB client.

    One instance manages all four collections. Documents are added with a
    stable id and metadata (language, user_id, etc.); queries return the
    nearest documents, optionally filtered by metadata.
    """

    def __init__(self, embedding_function: Any | None = None) -> None:
        # Lazy import so importing this module does not require chromadb until
        # a store is actually constructed.
        import chromadb

        self._client = chromadb.PersistentClient(path=str(_chroma_path()))

        ef: Any = embedding_function
        if ef is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            ef = DefaultEmbeddingFunction()
        self._embedding_function = ef

        self._collections: dict[str, Any] = {
            name: self._client.get_or_create_collection(
                name=name, embedding_function=ef
            )
            for name in COLLECTIONS
        }

    def _collection(self, name: str) -> Any:
        if name not in self._collections:
            raise ValueError(
                f"Unknown collection {name!r}. Valid: {', '.join(COLLECTIONS)}"
            )
        return self._collections[name]

    def add(
        self,
        collection: str,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add (or overwrite) documents in a collection.

        Uses ``upsert`` so re-adding the same id updates rather than errors.
        """
        self._collection(collection).upsert(
            ids=ids, documents=documents, metadatas=metadatas
        )

    def query(
        self,
        collection: str,
        *,
        text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search within a collection.

        Args:
            collection: One of :data:`COLLECTIONS`.
            text: The query text.
            n_results: Max results to return.
            where: Optional metadata filter (e.g. ``{"language": "Spanish"}``).

        Returns:
            A list of hits, each ``{"id", "document", "metadata", "distance"}``,
            nearest first.
        """
        result = self._collection(collection).query(
            query_texts=[text], n_results=n_results, where=where
        )
        return self._flatten(result)

    def count(self, collection: str) -> int:
        """Return the number of documents in a collection."""
        return int(self._collection(collection).count())

    @staticmethod
    def _flatten(result: dict[str, Any]) -> list[dict[str, Any]]:
        """Flatten Chroma's batched query result into a simple list of hits."""
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: list[dict[str, Any]] = []
        for i, doc_id in enumerate(ids):
            hits.append(
                {
                    "id": doc_id,
                    "document": documents[i] if i < len(documents) else None,
                    "metadata": metadatas[i] if i < len(metadatas) else None,
                    "distance": distances[i] if i < len(distances) else None,
                }
            )
        return hits


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Return a process-wide singleton vector store.

    Building the store loads the embedding model, so it is cached after first
    use. Tests that need isolation construct :class:`VectorStore` directly with
    a stub embedding function.
    """
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


def reset_vector_store() -> None:
    """Drop the cached singleton (used by tests to pick up a new chroma path)."""
    global _store
    _store = None
