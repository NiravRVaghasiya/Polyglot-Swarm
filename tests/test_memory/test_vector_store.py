"""Tests for the ChromaDB vector store wrapper.

A deterministic stub embedding function is injected so tests are fast, offline,
and have predictable nearest-neighbor ordering (no model download needed).
"""

from __future__ import annotations

import numpy as np
import pytest
from chromadb.api.types import EmbeddingFunction

from src.memory.vector_store import COLLECTIONS, VectorStore


class StubEmbeddingFunction(EmbeddingFunction):
    """Deterministic bag-of-words embedding over a tiny fixed vocabulary.

    Each dimension counts occurrences of a keyword, so documents sharing words
    with the query sit closer in vector space. Enough to assert ordering.
    Subclasses Chroma's EmbeddingFunction so query/doc paths both route here.
    """

    _VOCAB = ["table", "chair", "food", "bill", "dog", "cat", "run", "eat"]

    def __init__(self) -> None:
        pass

    def __call__(self, input):  # noqa: A002 - chroma requires this signature
        vectors = []
        for text in input:
            tokens = text.lower().split()
            vectors.append(
                np.array([float(tokens.count(word)) for word in self._VOCAB], dtype=np.float32)
            )
        return vectors

    @staticmethod
    def name() -> str:
        return "stub"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> StubEmbeddingFunction:
        return StubEmbeddingFunction()


@pytest.fixture
def store(temp_storage):
    return VectorStore(embedding_function=StubEmbeddingFunction())


class TestCollections:
    def test_all_collections_created(self, store):
        for name in COLLECTIONS:
            assert store.count(name) == 0

    def test_unknown_collection_raises(self, store):
        with pytest.raises(ValueError):
            store.query("not_a_collection", text="hi")


class TestAddAndQuery:
    def test_add_increments_count(self, store):
        store.add(
            "vocabulary",
            ids=["1"],
            documents=["table food bill"],
            metadatas=[{"language": "Spanish"}],
        )
        assert store.count("vocabulary") == 1

    def test_query_returns_nearest_first(self, store):
        store.add(
            "vocabulary",
            ids=["food_doc", "pet_doc"],
            documents=["food eat bill table", "dog cat run"],
            metadatas=[{"language": "Spanish"}, {"language": "Spanish"}],
        )
        hits = store.query("vocabulary", text="food eat", n_results=2)
        assert hits[0]["id"] == "food_doc"

    def test_query_metadata_filter(self, store):
        store.add(
            "vocabulary",
            ids=["es", "it"],
            documents=["food table", "food table"],
            metadatas=[{"language": "Spanish"}, {"language": "Italian"}],
        )
        hits = store.query("vocabulary", text="food", where={"language": "Italian"})
        assert len(hits) == 1
        assert hits[0]["id"] == "it"

    def test_upsert_overwrites(self, store):
        store.add("cultural_notes", ids=["n1"], documents=["dog"])
        store.add("cultural_notes", ids=["n1"], documents=["cat"])
        assert store.count("cultural_notes") == 1
        hits = store.query("cultural_notes", text="cat", n_results=1)
        assert hits[0]["document"] == "cat"

    def test_hit_shape(self, store):
        store.add(
            "grammar_rules",
            ids=["r1"],
            documents=["table"],
            metadatas=[{"category": "nouns"}],
        )
        hit = store.query("grammar_rules", text="table")[0]
        assert set(hit.keys()) == {"id", "document", "metadata", "distance"}
        assert hit["metadata"]["category"] == "nouns"


class TestPersistence:
    def test_survives_new_instance(self, temp_storage):
        s1 = VectorStore(embedding_function=StubEmbeddingFunction())
        s1.add("conversations", ids=["c1"], documents=["food table bill"])

        # A fresh instance pointed at the same path sees the data.
        s2 = VectorStore(embedding_function=StubEmbeddingFunction())
        assert s2.count("conversations") == 1
