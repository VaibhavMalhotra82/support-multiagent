import json
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from app.cache import CacheKey, cache
from app.config import settings
from app import observability
from app.contracts.schemas import QueryMetadata


def build_prompt(question: str, context: List[str], metadata: Optional[QueryMetadata]) -> str:
    prompt_sections = [
        "You are a technical support assistant.",
        f"Question: {question}",
    ]
    if metadata:
        prompt_sections.append(f"Metadata: {metadata.json()}")
    if context:
        prompt_sections.append("Context:")
        prompt_sections.extend(context)
    return "\n\n".join(prompt_sections)


def retrieve_documents(question: str, metadata: Optional[QueryMetadata]) -> List[Dict[str, Any]]:
    observability.log_step("retrieval.start", "document_retrieval_started")
    metadata_dict = _metadata_dict(metadata)
    cache_key = CacheKey.build("retrieval", question, metadata_dict)
    cached = cache.get(cache_key)
    if cached:
        observability.log_step("retrieval.cache", "retrieval_cache_hit=true")
        return json.loads(cached)

    collection = _get_collection()
    if collection.count() == 0:
        cache.set(cache_key, "[]", ttl=300)
        return []
    stored_metadata = collection.get(include=["metadatas"]).get("metadatas", [])
    available_keys = {
        key
        for item in stored_metadata
        for key in (item or {}).keys()
    }
    supported_metadata = {
        key: value for key, value in metadata_dict.items() if key in available_keys
    }
    where = _build_where(supported_metadata)
    ignored_metadata = sorted(set(metadata_dict) - set(supported_metadata))
    if ignored_metadata:
        observability.log_step(
            "retrieval.filters",
            f"ignored_metadata={','.join(ignored_metadata)}",
        )
    dense = collection.query(
        query_texts=[question],
        n_results=settings.retrieval_top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    candidates = _dense_candidates(dense)
    corpus = collection.get(where=where, include=["documents", "metadatas"])
    sparse_scores = _sparse_scores(question, corpus)
    for candidate in candidates:
        candidate["sparse_score"] = sparse_scores.get(candidate["id"], 0.0)
        candidate["score"] = 0.65 * candidate["dense_score"] + 0.35 * candidate["sparse_score"]
    results = rerank_documents(question, candidates)[: settings.retrieval_top_k]
    cache.set(cache_key, json.dumps(results), ttl=300)
    observability.log_step("retrieval.complete", f"documents={len(results)}")
    return results


def _metadata_dict(metadata: Optional[QueryMetadata]) -> Dict[str, Any]:
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return {key: value for key, value in metadata.items() if value is not None}
    return metadata.dict(exclude_none=True)


def _build_where(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    filters = []
    for key, value in metadata.items():
        if isinstance(value, list):
            value = ",".join(str(item) for item in value)
        filters.append({key: value})
    if not filters:
        return None
    return filters[0] if len(filters) == 1 else {"$and": filters}


def _get_collection():
    import chromadb

    client = chromadb.PersistentClient(path=settings.chroma_path)
    return client.get_or_create_collection(name=settings.chroma_collection)


def _dense_candidates(query_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = []
    for doc_id, text, item_metadata, distance in zip(
        query_result.get("ids", [[]])[0],
        query_result.get("documents", [[]])[0],
        query_result.get("metadatas", [[]])[0],
        query_result.get("distances", [[]])[0],
    ):
        item_metadata = item_metadata or {}
        results.append({
            "id": doc_id,
            "text": text,
            "source": item_metadata.get("source", "unknown"),
            "metadata": item_metadata,
            "dense_score": 1.0 / (1.0 + max(float(distance), 0.0)),
        })
    return results


def _sparse_scores(question: str, corpus: Dict[str, Any]) -> Dict[str, float]:
    terms = re.findall(r"\w+", question.lower())
    query_terms = Counter(terms)
    scores = {}
    for doc_id, document in zip(corpus.get("ids", []), corpus.get("documents", [])):
        words = Counter(re.findall(r"\w+", (document or "").lower()))
        overlap = sum(min(query_terms[term], words[term]) for term in query_terms)
        denominator = math.sqrt(sum(query_terms.values()) * sum(words.values()))
        scores[doc_id] = overlap / denominator if overlap and denominator else 0.0
    return scores


def rerank_documents(question: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def generate_answer(prompt: str, retrieved: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "answer": f"Generated answer for: {prompt.splitlines()[1]}",
        "sources": [item["source"] for item in retrieved],
        "confidence": 0.78,
    }
