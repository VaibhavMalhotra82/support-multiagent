import json
from typing import Any, Dict, List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app import db, observability
from app.contracts.schemas import QueryMetadata


class ConversationMemory:
    def __init__(self):
        self.sessions: Dict[str, List[str]] = {}

    def add_turn(self, session_id: str, turn: str) -> None:
        self.sessions.setdefault(session_id, []).append(turn)

    def get_recent(self, session_id: str, limit: int = 5) -> List[str]:
        return self.sessions.get(session_id, [])[-limit:]


def get_recent_messages(
    session: Session,
    session_id: str,
    user_id: int,
    tenant_id: Optional[int],
    limit: int = 10,
) -> List[Dict[str, str]]:
    """Load recent turns only when the session belongs to this user and tenant."""
    messages = (
        session.query(db.ConversationMessage)
        .filter(
            and_(
                db.ConversationMessage.session_id == session_id,
                db.ConversationMessage.user_id == user_id,
                db.ConversationMessage.tenant_id == tenant_id,
            )
        )
        .order_by(db.ConversationMessage.created_at.desc(), db.ConversationMessage.id.desc())
        .limit(limit)
        .all()
    )
    result = [{"role": message.role, "content": message.content} for message in reversed(messages)]
    observability.log_step("memory.history.load", f"messages={len(result)}")
    return result


def get_history_messages(
    session: Session,
    session_id: str,
    user_id: int,
    tenant_id: Optional[int],
) -> List[db.ConversationMessage]:
    return (
        session.query(db.ConversationMessage)
        .filter(
            and_(
                db.ConversationMessage.session_id == session_id,
                db.ConversationMessage.user_id == user_id,
                db.ConversationMessage.tenant_id == tenant_id,
            )
        )
        .order_by(db.ConversationMessage.created_at.asc(), db.ConversationMessage.id.asc())
        .all()
    )


def session_belongs_to_user(
    session: Session,
    session_id: str,
    user_id: int,
    tenant_id: Optional[int],
) -> bool:
    return (
        session.query(db.ConversationMessage.id)
        .filter(
            and_(
                db.ConversationMessage.session_id == session_id,
                db.ConversationMessage.user_id == user_id,
                db.ConversationMessage.tenant_id == tenant_id,
            )
        )
        .first()
        is not None
    )


def add_exchange(
    session: Session,
    *,
    session_id: str,
    request_id: str,
    user_id: int,
    tenant_id: Optional[int],
    question: str,
    answer: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    metadata_json = json.dumps(metadata) if metadata else None
    session.add_all(
        [
            db.ConversationMessage(
                session_id=session_id,
                request_id=request_id,
                user_id=user_id,
                tenant_id=tenant_id,
                role="user",
                content=question,
                metadata_json=metadata_json,
            ),
            db.ConversationMessage(
                session_id=session_id,
                request_id=request_id,
                user_id=user_id,
                tenant_id=tenant_id,
                role="assistant",
                content=answer,
                metadata_json=metadata_json,
            ),
        ]
    )
    observability.log_step("memory.exchange.stage", "conversation_exchange_staged")


def add_long_term_record(
    session: Session,
    *,
    session_id: str,
    user_id: int,
    tenant_id: Optional[int],
    summary: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> db.LongTermMemoryRecord:
    record = db.LongTermMemoryRecord(
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        summary=summary,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    session.add(record)
    observability.log_step("memory.long_term.stage", "long_term_memory_staged")
    return record


def retrieve_semantic_memories(
    question: str,
    *,
    user_id: int,
    tenant_id: Optional[int],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Query the rebuildable semantic index, returning no data on index failure."""
    try:
        import chromadb
        from app.config import settings

        collection = chromadb.PersistentClient(path=settings.chroma_path).get_or_create_collection(
            name=settings.chroma_memory_collection
        )
        if collection.count() == 0:
            observability.log_step("memory.semantic.retrieve", "index_empty")
            return []
        result = collection.query(
            query_texts=[question],
            n_results=limit,
            where={
                "$and": [
                    {"user_id": str(user_id)},
                    {"tenant_id": str(tenant_id) if tenant_id is not None else "none"},
                ]
            },
            include=["documents", "metadatas", "distances"],
        )
        memories = []
        for summary, metadata, distance in zip(
            result.get("documents", [[]])[0],
            result.get("metadatas", [[]])[0],
            result.get("distances", [[]])[0],
        ):
            memories.append({"summary": summary, "metadata": metadata or {}, "distance": distance})
        observability.log_step("memory.semantic.retrieve", f"memories={len(memories)}")
        return memories
    except Exception:
        observability.log_step("memory.semantic.retrieve", "index_unavailable", level=30)
        return []


def index_semantic_memory(record: db.LongTermMemoryRecord) -> None:
    """Index one committed SQL record; SQL remains authoritative if this fails."""
    import chromadb
    from app.config import settings

    collection = chromadb.PersistentClient(path=settings.chroma_path).get_or_create_collection(
        name=settings.chroma_memory_collection
    )
    collection.upsert(
        ids=[str(record.id)],
        documents=[record.summary],
        metadatas=[
            {
                "user_id": str(record.user_id),
                "tenant_id": str(record.tenant_id) if record.tenant_id is not None else "none",
                "session_id": record.session_id,
                "record_id": str(record.id),
            }
        ],
    )
    observability.log_step("memory.semantic.index", "memory_indexed")


class LongTermMemory:
    def __init__(self):
        self.records: List[Dict[str, str]] = []

    def add_record(self, summary: str, metadata: Optional[QueryMetadata] = None) -> None:
        self.records.append({"summary": summary, "metadata": metadata.json() if metadata else ""})

    def retrieve(self, metadata: Optional[QueryMetadata] = None) -> List[str]:
        if not metadata:
            return [record["summary"] for record in self.records]
        return [record["summary"] for record in self.records if metadata.json() in record["metadata"]]


conversation_memory = ConversationMemory()
long_term_memory = LongTermMemory()
