import json
import logging
import time
from typing import Any, Dict, List

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import HumanMessage, SystemMessage

from app import cache, memory, observability
from app.persistence import rca
from app.knowledge import retrieval
from app.contracts.state import SupportAgentState
from app.workflow import prompts

# Initialize a placeholder LLM (should be injected from config)
llm: BaseLanguageModel = None


def set_llm(language_model: BaseLanguageModel) -> None:
    global llm
    llm = language_model


def _invoke_llm(messages: List[Any], state: SupportAgentState, step: str) -> Any:
    started_at = time.perf_counter()
    response = llm.invoke(messages)
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    usage = getattr(response, "usage_metadata", None) or {}
    response_metadata = getattr(response, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage", {}) or {}
    input_tokens = usage.get("input_tokens", token_usage.get("prompt_tokens", "-"))
    output_tokens = usage.get("output_tokens", token_usage.get("completion_tokens", "-"))
    total_tokens = usage.get("total_tokens", token_usage.get("total_tokens", "-"))
    model_name = response_metadata.get("model_name", getattr(llm, "model_name", "unknown"))
    observability.log_step(
        "llm.call",
        f"workflow_step={step} model={model_name} latency_ms={elapsed_ms} "
        f"input_tokens={input_tokens} output_tokens={output_tokens} total_tokens={total_tokens}",
        request_id=state.request_id,
    )
    return response


def classify_intent(state: SupportAgentState) -> SupportAgentState:
    """Classify the user's query intent."""
    if not llm:
        state.intent = "unknown"
        state.intent_confidence = 0.5
        return state

    try:
        prompt = prompts.INTENT_CLASSIFIER_PROMPT.format_prompt(question=state.question)
        response = _invoke_llm(prompt.to_messages(), state, "classify_intent")
        content = response.content.strip().lower()

        valid_intents = ["troubleshooting", "known_issue", "policy", "escalation", "other"]
        state.intent = content if content in valid_intents else "other"
        state.intent_confidence = 0.8

        observability.log_step("workflow.classify_intent", f"intent={state.intent} confidence={state.intent_confidence}", request_id=state.request_id)
    except Exception as e:
        observability.log_step("workflow.classify_intent", f"error={str(e)}", request_id=state.request_id, level=logging.ERROR)
        state.intent = "other"
        state.intent_confidence = 0.3

    return state


def retrieve_documents(state: SupportAgentState) -> SupportAgentState:
    """Retrieve relevant documents from knowledge base."""
    try:
        # Check cache first
        cache_key = cache.CacheKey.build("retrieval", state.question, state.metadata)
        cached = cache.cache.get(cache_key)
        if cached:
            state.retrieved_documents = json.loads(cached)
            state.retrieval_cache_hit = True
            observability.log_step("workflow.retrieve_documents", "cache_hit=true", request_id=state.request_id)
            return state

        # Perform hybrid retrieval (placeholder)
        docs = retrieval.retrieve_documents(state.question, state.metadata)
        state.retrieved_documents = docs
        state.retrieval_confidence = sum(doc.get("score", 0) for doc in docs) / len(docs) if docs else 0.0
        state.search_terms = [state.question]  # Placeholder

        # Cache the result
        cache.cache.set(cache_key, json.dumps(docs), ttl=300)

        observability.log_step(
            "workflow.retrieve_documents",
            f"retrieval_confidence={state.retrieval_confidence} docs_retrieved={len(docs)}",
            request_id=state.request_id,
        )
    except Exception as e:
        observability.log_step("workflow.retrieve_documents", f"error={str(e)}", request_id=state.request_id, level=logging.ERROR)
        state.retrieved_documents = []
        state.retrieval_confidence = 0.0

    return state


def generate_answer(state: SupportAgentState) -> SupportAgentState:
    """Generate an answer using retrieved documents."""
    if not llm:
        state.answer = "Unable to generate answer: LLM not configured."
        state.answer_sources = []
        return state

    try:
        documents_text = "\n".join(
            [f"- {doc.get('text', 'N/A')} (source: {doc.get('source', 'unknown')})" for doc in state.retrieved_documents]
        )

        memory_text = ""
        history_text = "\n".join(
            f"user: {turn['content']}"
            for turn in state.conversation_history[-6:]
            if turn.get("role") == "user"
        )
        prompt = prompts.ANSWER_PROMPT.format_prompt(
            question=state.question,
            history=history_text,
            documents=documents_text,
            memories=memory_text,
        )
        response = _invoke_llm(prompt.to_messages(), state, "generate_answer")

        state.answer = response.content
        state.answer_sources = [doc.get("source", "unknown") for doc in state.retrieved_documents]

        observability.log_step("workflow.generate_answer", f"answer_generated=true sources={len(state.answer_sources)}", request_id=state.request_id)
    except Exception as e:
        observability.log_step("workflow.generate_answer", f"error={str(e)}", request_id=state.request_id, level=logging.ERROR)
        state.answer = "Error generating answer. Escalating to human support."
        state.should_escalate = True

    return state


def score_confidence(state: SupportAgentState) -> SupportAgentState:
    """Score confidence in the generated answer."""
    if not llm:
        state.confidence_score = 0.5
        return state

    try:
        prompt = prompts.CONFIDENCE_PROMPT.format_prompt(
            question=state.question, answer=state.answer or "N/A", retrieval_score=state.retrieval_confidence
        )
        response = _invoke_llm(prompt.to_messages(), state, "score_confidence")
        content = response.content.strip()

        try:
            result = json.loads(content)
            state.confidence_score = result.get("confidence", 0.5)
        except json.JSONDecodeError:
            state.confidence_score = state.retrieval_confidence

        observability.log_step("workflow.score_confidence", f"confidence_score={state.confidence_score}", request_id=state.request_id)
    except Exception as e:
        observability.log_step("workflow.score_confidence", f"error={str(e)}", request_id=state.request_id, level=logging.ERROR)
        state.confidence_score = state.retrieval_confidence

    return state


def analyze_root_cause(state: SupportAgentState) -> SupportAgentState:
    """Analyze potential root causes and resolutions."""
    if not llm or state.confidence_score < 0.6:
        return state

    try:
        context = "\n".join([doc.get("text", "") for doc in state.retrieved_documents[:3]])
        history = "\n".join(
            f"{turn['role']}: {turn['content']}" for turn in state.conversation_history[-6:]
        )
        prompt = prompts.RCA_PROMPT.format_prompt(
            question=state.question, context=context, history=history
        )
        response = _invoke_llm(prompt.to_messages(), state, "analyze_root_cause")
        content = response.content.strip()

        try:
            result = json.loads(content)
            state.root_cause = result.get("root_cause", "Unknown")
            state.resolution = result.get("resolution", "Contact support")
        except json.JSONDecodeError:
            state.root_cause = "Unable to determine"
            state.resolution = "Escalate to specialist"

        observability.log_step("workflow.analyze_root_cause", f"rca_analysis=true root_cause={state.root_cause}", request_id=state.request_id)
    except Exception as e:
        observability.log_step("workflow.analyze_root_cause", f"error={str(e)}", request_id=state.request_id, level=logging.ERROR)

    return state


def decide_escalation(state: SupportAgentState) -> SupportAgentState:
    """Decide whether to escalate to human support."""
    if not llm:
        state.should_escalate = state.confidence_score < 0.5
        return state

    try:
        history = "\n".join([f"{turn['role']}: {turn['content']}" for turn in state.conversation_history[-3:]])
        prompt = prompts.ESCALATION_PROMPT.format_prompt(
            question=state.question, confidence=state.confidence_score, history=history
        )
        response = _invoke_llm(prompt.to_messages(), state, "decide_escalation")
        content = response.content.strip()

        try:
            result = json.loads(content)
            state.should_escalate = result.get("should_escalate", state.confidence_score < 0.5)
            state.escalation_reason = result.get("reason", "Low confidence")
        except json.JSONDecodeError:
            state.should_escalate = state.confidence_score < 0.5

        observability.log_step(
            "workflow.decide_escalation",
            f"escalation_decision={state.should_escalate} reason={state.escalation_reason}",
            request_id=state.request_id,
        )
    except Exception as e:
        observability.log_step("workflow.decide_escalation", f"error={str(e)}", request_id=state.request_id, level=logging.ERROR)
        state.should_escalate = True

    return state


def persist_response(state: SupportAgentState) -> SupportAgentState:
    """Persist the response to memory and storage."""
    try:
        # Store RCA if confidence is high
        if state.confidence_score > 0.7 and state.root_cause:
            from sqlalchemy.orm import Session
            from app import db
            session = db.SessionLocal()
            try:
                rca.create_rca_record(
                    session,
                    symptom=state.question,
                    root_cause=state.root_cause,
                    resolution=state.resolution,
                    tenant_id=state.tenant_id,
                )
            finally:
                session.close()

        observability.log_step("workflow.persist_response", "response_persisted=true", request_id=state.request_id)
    except Exception as e:
        observability.log_step("workflow.persist_response", f"error={str(e)}", request_id=state.request_id, level=logging.ERROR)

    return state
