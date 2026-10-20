import unittest
from unittest.mock import patch

from app import cache
from app.contracts.schemas import QueryMetadata
from app.knowledge import retrieval


class _Collection:
    def count(self):
        return 1

    def get(self, **kwargs):
        return {
            "ids": ["doc-1"],
            "documents": ["MkDocs Installation Requirements"],
            "metadatas": [{"source": "https://www.mkdocs.org/user-guide/installation/"}],
        }

    def query(self, **kwargs):
        self.where = kwargs["where"]
        return {
            "ids": [["doc-1"]],
            "documents": [["MkDocs Installation Requirements"]],
            "metadatas": [[{"source": "https://www.mkdocs.org/user-guide/installation/"}]],
            "distances": [[0.1]],
        }


class RetrievalTests(unittest.TestCase):
    def test_ignores_metadata_fields_absent_from_ingested_documents(self):
        collection = _Collection()
        cache.cache.clear()
        with patch.object(retrieval, "_get_collection", return_value=collection):
            results = retrieval.retrieve_documents(
                "Installation",
                QueryMetadata(product="MyApp", version="1.2.0", language="en"),
            )

        self.assertEqual(len(results), 1)
        self.assertIn("mkdocs.org/user-guide/installation", results[0]["source"])
        self.assertIsNone(collection.where)


if __name__ == "__main__":
    unittest.main()
