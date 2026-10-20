from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SupportAgentState:
    """
    State for the multi-agent support system.
    Tracks the progression of a user query through multiple agent steps.
    """

    # Input
    question: str
    session_id: str
    user_id: Optional[int] = None
    tenant_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    # Classification
    intent: Optional[str] = None
    intent_confidence: float = 0.0

    # Retrieval
    search_terms: List[str] = field(default_factory=list)
    retrieved_documents: List[Dict[str, Any]] = field(default_factory=list)
    retrieval_confidence: float = 0.0
    retrieval_cache_hit: bool = False

    # Generation
    answer: Optional[str] = None
    answer_sources: List[str] = field(default_factory=list)

    # Confidence and RCA
    confidence_score: float = 0.0
    root_cause: Optional[str] = None
    resolution: Optional[str] = None

    # Escalation
    should_escalate: bool = False
    escalation_reason: Optional[str] = None

    # Memory and Observability
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    semantic_memories: List[Dict[str, Any]] = field(default_factory=list)
    request_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Feedback and RCA Storage
    feedback_helpful: Optional[bool] = None
    feedback_comment: Optional[str] = None
