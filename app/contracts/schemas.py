from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    roles: List[str]


class LogoutResponse(BaseModel):
    status: str


class QueryMetadata(BaseModel):
    product: Optional[str] = None
    version: Optional[str] = None
    tier: Optional[str] = None
    language: Optional[str] = None
    tags: Optional[List[str]] = None
    tenant_id: Optional[str] = None


class QueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    metadata: Optional[QueryMetadata] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[str]
    confidence: float
    cache_hit: bool = False
    request_id: Optional[str] = None
    session_id: str


class HistoryMessage(BaseModel):
    session_id: str
    request_id: str
    role: str
    content: str
    created_at: datetime


class HistoryResponse(BaseModel):
    items: List[HistoryMessage]
    total: int


class RCARecordCreate(BaseModel):
    symptom: str
    root_cause: str
    resolution: str
    product: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None
    tenant_id: Optional[str] = None


class RCARecordResponse(BaseModel):
    id: int
    symptom: str
    root_cause: str
    resolution: str
    product: Optional[str] = None
    version: Optional[str] = None
    tags: Optional[List[str]] = None
    tenant_id: Optional[str] = None
    created_at: str


class FeedbackRequest(BaseModel):
    request_id: str
    helpful: bool
    comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    status: str
    updated: bool


class AdminStatsResponse(BaseModel):
    active_users: int
    resolved_queries: int
    cache_hit_rate: float
    open_escalations: int


class AdminUserDetail(BaseModel):
    id: int
    username: str
    active: bool
    tenant_id: Optional[int] = None


class AdminQueryDetail(BaseModel):
    request_id: str
    session_id: Optional[str] = None
    username: str
    resolved: bool
    cache_hit: bool
    created_at: datetime


class AdminEscalationDetail(BaseModel):
    request_id: str
    username: str
    reason: Optional[str] = None
    status: str
    created_at: datetime


class AdminUserDetailResponse(BaseModel):
    items: List[AdminUserDetail]
    total: int


class AdminQueryDetailResponse(BaseModel):
    items: List[AdminQueryDetail]
    total: int


class AdminEscalationDetailResponse(BaseModel):
    items: List[AdminEscalationDetail]
    total: int


class AdminActivityItem(BaseModel):
    id: int
    username: str
    event_type: str
    description: str
    created_at: datetime


class AdminActivityResponse(BaseModel):
    items: List[AdminActivityItem]
    total: int


class IngestionRequest(BaseModel):
    source: str
    metadata: Optional[Dict[str, Any]] = None


class IngestionResponse(BaseModel):
    source: str
    chunks: int
    status: str


class DiagnosticsResponse(BaseModel):
    database: str
    knowledge_documents: int
    knowledge_chunks: int
