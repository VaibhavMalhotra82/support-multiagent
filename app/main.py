import os
import uuid
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from langsmith import traceable
from langchain_openai import ChatOpenAI

from app import auth, db, memory, observability
from app.knowledge import ingestion
from app.persistence import rca
from app.workflow.langgraph import create_support_workflow, execute_query
from app.contracts.state import SupportAgentState
from seed_db import ensure_default_data
from app.contracts.schemas import (
    AuthRequest,
    AuthResponse,
    AdminStatsResponse,
    AdminEscalationDetail,
    AdminEscalationDetailResponse,
    AdminActivityItem,
    AdminActivityResponse,
    AdminQueryDetail,
    AdminQueryDetailResponse,
    AdminUserDetail,
    AdminUserDetailResponse,
    DiagnosticsResponse,
    FeedbackRequest,
    FeedbackResponse,
    HistoryResponse,
    IngestionRequest,
    IngestionResponse,
    LogoutResponse,
    QueryRequest,
    QueryResponse,
    RCARecordCreate,
    RCARecordResponse,
)

app = FastAPI(title="Support Multi-Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request, call_next):
    request_id = str(uuid.uuid4())
    context_token = observability.set_request_id(request_id)
    try:
        return await call_next(request)
    finally:
        observability.reset_request_id(context_token)

# Initialize the multi-agent workflow (LLM can be injected based on config)
load_dotenv()

llm = ChatOpenAI(
    model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
    temperature=float(os.environ.get("LLM_TEMPERATURE", "0.2")),
    api_key=os.environ.get("OPENAI_API_KEY"),
)
support_workflow = create_support_workflow(llm=llm)


@app.on_event("startup")
def startup_event() -> None:
    db.init_db()
    session = db.SessionLocal()
    try:
        ensure_default_data(session)
    finally:
        session.close()
    observability.log_step("app.startup", "database_initialized")


@app.get("/login")
def login_compatibility() -> dict:
    return {
        "detail": "Login requires POST. Use POST /login or POST /auth/login with JSON: {\"username\": \"...\", \"password\": \"...\"}",
    }


@app.post("/auth/login", response_model=AuthResponse)
def auth_login(request: AuthRequest, db_session: Session = Depends(db.get_db)) -> AuthResponse:
    user = auth.authenticate_user(db_session, request.username, request.password)
    session_token = auth.create_session_token(db_session, user)
    db_session.add(db.ActivityEvent(user_id=user.id, event_type="login", description="Logged in"))
    db_session.commit()
    observability.log_auth(user.username, "login", True)
    return AuthResponse(
        access_token=session_token.token,
        username=user.username,
        roles=[role.name for role in user.roles],
    )


@app.post("/login", response_model=AuthResponse)
def login_alias(request: AuthRequest, db_session: Session = Depends(db.get_db)) -> AuthResponse:
    return auth_login(request, db_session)


def get_current_user(authorization: Optional[str] = Header(None), db_session: Session = Depends(db.get_db)) -> db.User:
    if not authorization or not authorization.startswith("Bearer "):
        observability.log_step("auth.get_current_user", "missing_authorization_header", level=30)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    token = authorization.split(" ", 1)[1]
    user = auth.get_user_from_token(db_session, token)
    if not user:
        observability.log_step("auth.get_current_user", "invalid_or_expired_token", level=30)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    observability.log_step("auth.get_current_user", "authenticated_request")
    return user


@app.post("/auth/logout", response_model=LogoutResponse)
def auth_logout(
    authorization: Optional[str] = Header(None),
    current_user: db.User = Depends(get_current_user),
    db_session: Session = Depends(db.get_db),
) -> LogoutResponse:
    revoked_sessions = auth.revoke_user_sessions(db_session, current_user.id)
    db_session.add(
        db.ActivityEvent(
            user_id=current_user.id,
            event_type="logout",
            description=f"Logged out ({revoked_sessions} session{'s' if revoked_sessions != 1 else ''} terminated)",
        )
    )
    db_session.commit()
    observability.log_step(
        "auth.logout",
        f"user={current_user.username} logout_completed sessions_revoked={revoked_sessions}",
    )
    return LogoutResponse(status="ok")


def get_admin_user(current_user: db.User = Depends(get_current_user)) -> db.User:
    if not any(role.name == "admin" for role in current_user.roles):
        observability.log_step("auth.get_admin_user", "admin_access_denied", level=30)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    observability.log_step("auth.get_admin_user", "admin_access_granted")
    return current_user


@app.get("/admin/stats", response_model=AdminStatsResponse)
def admin_stats(current_user: db.User = Depends(get_admin_user), db_session: Session = Depends(db.get_db)) -> AdminStatsResponse:
    total_queries = db_session.query(db.QueryRecord).count()
    cache_hits = db_session.query(db.QueryRecord).filter(db.QueryRecord.cache_hit.is_(True)).count()
    active_session_users = (
        db_session.query(db.SessionToken.user_id)
        .join(db.User, db.User.id == db.SessionToken.user_id)
        .filter(
            db.User.is_active.is_(True),
            db.SessionToken.expires_at >= datetime.utcnow(),
            db.SessionToken.revoked_at.is_(None),
        )
        .distinct()
        .count()
    )
    return AdminStatsResponse(
        active_users=active_session_users,
        resolved_queries=db_session.query(db.QueryRecord).filter(db.QueryRecord.resolved.is_(True)).count(),
        cache_hit_rate=round((cache_hits / total_queries) * 100, 1) if total_queries else 0.0,
        open_escalations=db_session.query(db.Escalation).filter(db.Escalation.status == "open").count(),
    )


@app.get("/admin/stats/active-users", response_model=AdminUserDetailResponse)
def admin_active_users(
    current_user: db.User = Depends(get_admin_user),
    db_session: Session = Depends(db.get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AdminUserDetailResponse:
    query = (
        db_session.query(db.User)
        .join(db.SessionToken, db.SessionToken.user_id == db.User.id)
        .filter(
            db.User.is_active.is_(True),
            db.SessionToken.expires_at >= datetime.utcnow(),
            db.SessionToken.revoked_at.is_(None),
        )
        .distinct()
        .order_by(db.User.username.asc())
    )
    total = query.count()
    users = query.offset(offset).limit(limit).all()
    return AdminUserDetailResponse(
        items=[AdminUserDetail(id=user.id, username=user.username, active=user.is_active, tenant_id=user.tenant_id) for user in users],
        total=total,
    )


def _query_detail_response(
    db_session: Session,
    query,
    limit: int,
    offset: int,
) -> AdminQueryDetailResponse:
    total = query.count()
    records = query.order_by(db.QueryRecord.created_at.desc(), db.QueryRecord.id.desc()).offset(offset).limit(limit).all()
    return AdminQueryDetailResponse(
        items=[
            AdminQueryDetail(
                request_id=record.request_id,
                session_id=record.session_id,
                username=record.user.username,
                resolved=record.resolved,
                cache_hit=record.cache_hit,
                created_at=record.created_at,
            )
            for record in records
        ],
        total=total,
    )


@app.get("/admin/stats/resolved-queries", response_model=AdminQueryDetailResponse)
def admin_resolved_queries(
    current_user: db.User = Depends(get_admin_user),
    db_session: Session = Depends(db.get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AdminQueryDetailResponse:
    return _query_detail_response(
        db_session,
        db_session.query(db.QueryRecord).filter(db.QueryRecord.resolved.is_(True)),
        limit,
        offset,
    )


@app.get("/admin/stats/cache-hits", response_model=AdminQueryDetailResponse)
def admin_cache_hits(
    current_user: db.User = Depends(get_admin_user),
    db_session: Session = Depends(db.get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AdminQueryDetailResponse:
    return _query_detail_response(
        db_session,
        db_session.query(db.QueryRecord).filter(db.QueryRecord.cache_hit.is_(True)),
        limit,
        offset,
    )


@app.get("/admin/stats/open-escalations", response_model=AdminEscalationDetailResponse)
def admin_open_escalations(
    current_user: db.User = Depends(get_admin_user),
    db_session: Session = Depends(db.get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AdminEscalationDetailResponse:
    query = db_session.query(db.Escalation).filter(db.Escalation.status == "open")
    total = query.count()
    escalations = query.order_by(db.Escalation.created_at.desc(), db.Escalation.id.desc()).offset(offset).limit(limit).all()
    return AdminEscalationDetailResponse(
        items=[
            AdminEscalationDetail(
                request_id=escalation.request_id,
                username=escalation.user.username,
                reason=escalation.reason,
                status=escalation.status,
                created_at=escalation.created_at,
            )
            for escalation in escalations
        ],
        total=total,
    )


@app.get("/admin/activity", response_model=AdminActivityResponse)
def admin_activity(
    current_user: db.User = Depends(get_admin_user),
    db_session: Session = Depends(db.get_db),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AdminActivityResponse:
    query = db_session.query(db.ActivityEvent).join(db.User).order_by(
        db.ActivityEvent.created_at.desc(), db.ActivityEvent.id.desc()
    )
    total = query.count()
    events = query.offset(offset).limit(limit).all()
    return AdminActivityResponse(
        items=[
            AdminActivityItem(
                id=event.id,
                username=event.user.username,
                event_type=event.event_type,
                description=event.description,
                created_at=event.created_at,
            )
            for event in events
        ],
        total=total,
    )


@app.post("/admin/ingest", response_model=IngestionResponse)
def admin_ingest(
    request: IngestionRequest,
    current_user: db.User = Depends(get_admin_user),
    db_session: Session = Depends(db.get_db),
) -> IngestionResponse:
    try:
        chunks = ingestion.ingest_document(request.source, metadata=request.metadata)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    db_session.add(db.ActivityEvent(user_id=current_user.id, event_type="ingestion", description=f"Ingested {request.source} ({chunks} chunks)"))
    db_session.commit()
    return IngestionResponse(source=request.source, chunks=chunks, status="ingested")


@app.post("/admin/sync", response_model=IngestionResponse)
def admin_sync(
    request: IngestionRequest,
    current_user: db.User = Depends(get_admin_user),
    db_session: Session = Depends(db.get_db),
) -> IngestionResponse:
    try:
        chunks = ingestion.ingest_document(request.source, metadata=request.metadata)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    db_session.add(db.ActivityEvent(user_id=current_user.id, event_type="sync", description=f"Synced {request.source} ({chunks} chunks)"))
    db_session.commit()
    return IngestionResponse(source=request.source, chunks=chunks, status="synced")


@app.get("/admin/diagnostics", response_model=DiagnosticsResponse)
def admin_diagnostics(current_user: db.User = Depends(get_admin_user), db_session: Session = Depends(db.get_db)) -> DiagnosticsResponse:
    try:
        collection = ingestion._collection()
        knowledge_chunks = collection.count()
        metadatas = collection.get(include=["metadatas"]).get("metadatas", [])
        knowledge_documents = len({item.get("document_id") for item in metadatas if item and item.get("document_id")})
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Knowledge store unavailable: {error}") from error
    db_session.add(
        db.ActivityEvent(
            user_id=current_user.id,
            event_type="diagnostics",
            description=f"Ran diagnostics ({knowledge_documents} documents, {knowledge_chunks} chunks)",
        )
    )
    db_session.commit()
    return DiagnosticsResponse(
        database="ok" if db_session.execute(text("SELECT 1")).scalar() == 1 else "unavailable",
        knowledge_documents=knowledge_documents,
        knowledge_chunks=knowledge_chunks,
    )


@app.post("/query", response_model=QueryResponse)
@traceable(name="support_query", tags=["support", "query"])
def query_endpoint(
    request: QueryRequest,
    current_user: db.User = Depends(get_current_user),
    db_session: Session = Depends(db.get_db),
) -> QueryResponse:
    auth.assert_permission(current_user, "query_support")

    request_id = observability.get_request_id() or str(uuid.uuid4())
    observability.log_request(request_id, request.dict())

    session_id = request.session_id or str(uuid.uuid4())
    if request.session_id and not memory.session_belongs_to_user(
        db_session, session_id, current_user.id, current_user.tenant_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Create initial state for the multi-agent workflow
    state = SupportAgentState(
        question=request.question,
        session_id=session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        metadata=request.metadata.dict() if request.metadata else None,
        request_id=request_id,
        conversation_history=memory.get_recent_messages(
            db_session, session_id, current_user.id, current_user.tenant_id
        ),
        semantic_memories=memory.retrieve_semantic_memories(
            request.question,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
        ),
    )

    # Execute the multi-agent workflow
    final_state = execute_query(support_workflow, state)

    db_session.add(db.QueryRecord(
        request_id=request_id,
        session_id=session_id,
        user_id=current_user.id,
        resolved=not final_state.should_escalate,
        cache_hit=final_state.retrieval_cache_hit,
        should_escalate=final_state.should_escalate,
    ))
    db_session.add(
        db.ActivityEvent(
            user_id=current_user.id,
            event_type="query",
            description=f"Submitted support query ({request.question[:80]})",
        )
    )
    if final_state.should_escalate:
        db_session.add(db.Escalation(
            request_id=request_id,
            user_id=current_user.id,
            reason=final_state.escalation_reason,
        ))
    memory.add_exchange(
        db_session,
        session_id=session_id,
        request_id=request_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        question=request.question,
        answer=final_state.answer or "Unable to generate answer",
        metadata=request.metadata.dict() if request.metadata else None,
    )
    long_term_record = memory.add_long_term_record(
        db_session,
        session_id=session_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        summary=f"Q: {request.question}\nA: {final_state.answer or 'Unable to generate answer'}",
        metadata=request.metadata.dict() if request.metadata else None,
    )
    db_session.commit()
    try:
        memory.index_semantic_memory(long_term_record)
    except Exception as error:
        observability.log_step(
            "memory.semantic_index",
            f"semantic_memory_index_failed={error}",
            request_id=request_id,
            level=30,
        )

    # Build response from workflow output
    response = QueryResponse(
        answer=final_state.answer or "Unable to generate answer",
        sources=final_state.answer_sources,
        confidence=final_state.confidence_score,
        cache_hit=final_state.retrieval_cache_hit,
        request_id=request_id,
        session_id=session_id,
    )

    observability.log_response(request_id, response.dict())
    return response


@app.get("/history", response_model=HistoryResponse)
def history_endpoint(
    session_id: Optional[str] = Query(None),
    current_user: db.User = Depends(get_current_user),
    db_session: Session = Depends(db.get_db),
) -> HistoryResponse:
    if not session_id:
        return HistoryResponse(items=[], total=0)

    messages = memory.get_history_messages(
        db_session, session_id, current_user.id, current_user.tenant_id
    )
    return HistoryResponse(items=messages, total=len(messages))


@app.post("/rca", response_model=RCARecordResponse)
def create_rca(record: RCARecordCreate, current_user: db.User = Depends(get_current_user), db_session: Session = Depends(db.get_db)) -> RCARecordResponse:
    auth.assert_permission(current_user, "manage_rca")
    created = rca.create_rca_record(
        db_session,
        symptom=record.symptom,
        root_cause=record.root_cause,
        resolution=record.resolution,
        product=record.product,
        version=record.version,
        tags=record.tags,
        tenant_id=record.tenant_id,
    )
    db_session.add(
        db.ActivityEvent(
            user_id=current_user.id,
            event_type="rca",
            description=f"Created RCA record ({record.symptom[:80]})",
        )
    )
    db_session.commit()
    return RCARecordResponse(
        id=created.id,
        symptom=created.symptom,
        root_cause=created.root_cause,
        resolution=created.resolution,
        product=created.product,
        version=created.version,
        tags=created.tags.split(",") if created.tags else None,
        tenant_id=created.tenant_id,
        created_at=created.created_at.isoformat(),
    )


@app.post("/feedback", response_model=FeedbackResponse)
def feedback_endpoint(request: FeedbackRequest, current_user: db.User = Depends(get_current_user), db_session: Session = Depends(db.get_db)) -> FeedbackResponse:
    auth.assert_permission(current_user, "submit_feedback")
    feedback = db.Feedback(request_id=request.request_id, helpful=request.helpful, comment=request.comment)
    db_session.add(feedback)
    db_session.add(
        db.ActivityEvent(
            user_id=current_user.id,
            event_type="feedback",
            description=f"Submitted {'helpful' if request.helpful else 'unhelpful'} feedback",
        )
    )
    db_session.commit()
    return FeedbackResponse(status="ok", updated=True)
