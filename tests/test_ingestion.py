import unittest
from unittest.mock import MagicMock, patch

from app import cache
from app.knowledge import ingestion


class IngestionCrawlerTests(unittest.TestCase):
    def test_crawls_same_subtree_and_normalizes_links(self):
        pages = {
            "https://docs.example/user-guide": [
                "configuration/",
                "/user-guide/install/#setup",
                "https://docs.example/user-guide/configuration/?view=full",
                "/about/",
                "https://other.example/user-guide/",
            ],
            "https://docs.example/user-guide/configuration/": [],
            "https://docs.example/user-guide/install/": [],
        }

        def fake_read_url(url):
            return url, "page", pages[url], {}

        with patch.object(ingestion, "_read_url", side_effect=fake_read_url):
            result = ingestion._crawl_url_tree("https://docs.example/user-guide")

        self.assertEqual(
            result,
            [
                "https://docs.example/user-guide",
                "https://docs.example/user-guide/configuration/",
                "https://docs.example/user-guide/install/",
            ],
        )

    def test_root_fetch_errors_are_not_silenced(self):
        with patch.object(ingestion, "_read_url", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                ingestion._crawl_url_tree("https://docs.example/user-guide")

    def test_ingestion_clears_cached_retrievals(self):
        cache_key = cache.CacheKey.build("retrieval", "Installation", {})
        cache.cache.set(cache_key, "old-result", ttl=300)
        collection = MagicMock()
        collection.get.return_value = {"ids": []}

        with patch.object(ingestion, "_collection", return_value=collection), patch.object(
            ingestion, "_read_source", return_value=("docs.txt", "new documentation", {})
        ):
            ingestion.ingest_documents(["docs.txt"])

        self.assertIsNone(cache.cache.get(cache_key))

    def test_local_source_metadata_is_stored_with_explicit_metadata(self):
        collection = MagicMock()
        collection.get.return_value = {"ids": []}

        with patch.object(ingestion, "_collection", return_value=collection), patch.object(
            ingestion,
            "_read_source",
            return_value=(
                "C:\\docs\\guide.txt",
                "installation requirements",
                {"content_type": "text/plain", "file_extension": ".txt", "file_name": "guide.txt"},
            ),
        ):
            ingestion.ingest_documents(
                ["guide.txt"],
                metadata={"product": "MkDocs", "tags": ["installation", "docs"]},
            )

        metadata = collection.add.call_args.kwargs["metadatas"][0]
        self.assertEqual(metadata["content_type"], "text/plain")
        self.assertEqual(metadata["file_extension"], ".txt")
        self.assertEqual(metadata["file_name"], "guide.txt")
        self.assertEqual(metadata["product"], "MkDocs")
        self.assertEqual(metadata["tags"], "installation,docs")

    def test_html_source_metadata_includes_title_and_meta_tags(self):
        parser = ingestion._HTMLTextParser()
        parser.feed(
            '<html><head><title>MkDocs Guide</title>'
            '<meta name="product" content="MkDocs">'
            '<meta property="og:type" content="article"></head>'
            '<body>Installation</body></html>'
        )

        self.assertEqual(parser.title_parts, ["MkDocs Guide"])
        self.assertEqual(parser.metadata["html_meta_product"], "MkDocs")
        self.assertEqual(parser.metadata["html_meta_og_type"], "article")


if __name__ == "__main__":
    unittest.main()
