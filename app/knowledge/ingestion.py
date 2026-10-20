"""Chunk local files or URLs and persist them in the support Chroma collection."""

import hashlib
import mimetypes
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app import cache, observability


MAX_CRAWL_PAGES = 100


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: List[str] = []
        self.links: List[str] = []
        self.metadata: Dict[str, str] = {}
        self.title_parts: List[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            attributes = dict(attrs)
            key = attributes.get("name") or attributes.get("property")
            value = attributes.get("content")
            if key and value:
                self.metadata[f"html_meta_{key.lower().replace(':', '_')}"] = value.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())
        if self._in_title and data.strip():
            self.title_parts.append(data.strip())


def _read_url(source: str) -> tuple[str, str, List[str], Dict[str, Any]]:
    request = Request(source, headers={"User-Agent": "support-multiagent/1.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read()
        content_type = response.headers.get_content_type()
    text = body.decode("utf-8", errors="replace")
    links: List[str] = []
    source_metadata: Dict[str, Any] = {
        "content_type": content_type,
        "file_extension": Path(urlparse(source).path).suffix.lower(),
        "url_host": urlparse(source).netloc,
        "url_path": urlparse(source).path or "/",
    }
    if content_type == "text/html" or urlparse(source).path.endswith((".html", ".htm")):
        parser = _HTMLTextParser()
        parser.feed(text)
        text = "\n".join(parser.parts)
        links = parser.links
        if parser.title_parts:
            source_metadata["title"] = " ".join(parser.title_parts)
        source_metadata.update(parser.metadata)
    return source, text, links, source_metadata


def _read_source(source: Union[str, Path]) -> tuple[str, str, Dict[str, Any]]:
    source_value = str(source)
    parsed = urlparse(source_value)
    if parsed.scheme in {"http", "https"}:
        source_name, text, _, source_metadata = _read_url(source_value)
        return source_name, text, source_metadata

    path = Path(source_value)
    source_name = str(path.resolve())
    return source_name, path.read_text(encoding="utf-8"), {
        "content_type": mimetypes.guess_type(source_name)[0] or "text/plain",
        "file_extension": path.suffix.lower(),
        "file_name": path.name,
    }


def _normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query=""))


def _is_child_url(url: str, root: str) -> bool:
    candidate = urlparse(url)
    root_url = urlparse(root)
    if candidate.scheme != root_url.scheme or candidate.netloc.lower() != root_url.netloc.lower():
        return False
    root_path = root_url.path.rstrip("/") or "/"
    candidate_path = candidate.path.rstrip("/") or "/"
    return candidate_path == root_path or candidate_path.startswith(f"{root_path}/")


def _crawl_url_tree(root: str) -> List[str]:
    root = _normalize_url(root)
    parsed_root = urlparse(root)
    join_root = root if parsed_root.path.endswith("/") else f"{root}/"
    queued = deque([root])
    visited = set()
    sources: List[str] = []

    while queued and len(sources) < MAX_CRAWL_PAGES:
        current = queued.popleft()
        if current in visited:
            continue
        visited.add(current)
        try:
            source_name, _, links, _ = _read_url(current)
        except (OSError, ValueError) as error:
            if current == root:
                raise
            observability.log_step("ingestion.crawl", f"page_skipped url={current} error={error}", level=30)
            continue

        sources.append(source_name)
        for link in links:
            child = _normalize_url(urljoin(join_root if current == root else current, link))
            if child not in visited and _is_child_url(child, root):
                queued.append(child)

    observability.log_step("ingestion.crawl", f"root={root} pages={len(sources)}")
    return sources


def _metadata_value(value: Any) -> Union[str, int, float, bool]:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if value is None:
        return ""
    return value


def _collection():
    import chromadb

    client = chromadb.PersistentClient(path=settings.chroma_path)
    return client.get_or_create_collection(name=settings.chroma_collection)


def ingest_documents(
    sources: Iterable[Union[str, Path]],
    metadata: Optional[Dict[str, Any]] = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> int:
    """Ingest sources and return the number of stored chunks."""
    observability.log_step("ingestion.start", "document_ingestion_started")
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    collection = _collection()
    common_metadata = {key: _metadata_value(value) for key, value in (metadata or {}).items() if value is not None}
    total = 0
    expanded_sources: List[Union[str, Path]] = []
    for source in sources:
        source_value = str(source)
        if urlparse(source_value).scheme in {"http", "https"}:
            expanded_sources.extend(_crawl_url_tree(source_value))
        else:
            expanded_sources.append(source)

    for source in expanded_sources:
        source_name, text, source_metadata = _read_source(source)
        chunks = [chunk for chunk in splitter.split_text(text) if chunk.strip()]
        document_id = hashlib.sha256(source_name.encode("utf-8")).hexdigest()[:16]
        old = collection.get(where={"document_id": document_id}, include=[])
        if old["ids"]:
            collection.delete(ids=old["ids"])

        ids = [f"{document_id}-{index}" for index in range(len(chunks))]
        chunk_metadata = [
            {
                **source_metadata,
                **common_metadata,
                "document_id": document_id,
                "source": source_name,
                "source_type": "url" if urlparse(source_name).scheme in {"http", "https"} else "file",
                "chunk_index": index,
            }
            for index in range(len(chunks))
        ]
        if chunks:
            collection.add(ids=ids, documents=chunks, metadatas=chunk_metadata)
            total += len(chunks)
    cache.cache.clear()
    observability.log_step("ingestion.complete", f"chunks={total}")
    return total


def ingest_document(source: Union[str, Path], metadata: Optional[Dict[str, Any]] = None) -> int:
    return ingest_documents([source], metadata=metadata)