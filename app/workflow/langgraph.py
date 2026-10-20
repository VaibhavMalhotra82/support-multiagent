from typing import Mapping, Optional

from langgraph.graph import StateGraph, END
from langchain_core.language_models import BaseLanguageModel

from app.workflow import agents
from app.contracts.state import SupportAgentState
from app import observability


def create_support_workflow(llm: Optional[BaseLanguageModel] = None) -> StateGraph:
    """
    Create the multi-agent support workflow using LangGraph StateGraph.

    Workflow stages:
    1. classify_intent - Determine the type of support query
    2. retrieve_documents - Fetch relevant knowledge base articles
    3. generate_answer - Create an answer based on retrieved docs
    4. score_confidence - Evaluate confidence in the answer
    5. analyze_root_cause - Deep dive into root causes if needed
    6. decide_escalation - Determine if human escalation is needed
    7. persist_response - Store conversation and RCA in memory

    Returns:
        A compiled StateGraph ready for execution
    """
    if llm:
        agents.set_llm(llm)

    workflow = StateGraph(SupportAgentState)

    # Add nodes
    workflow.add_node("classify_intent", agents.classify_intent)
    workflow.add_node("retrieve_documents", agents.retrieve_documents)
    workflow.add_node("generate_answer", agents.generate_answer)
    workflow.add_node("score_confidence", agents.score_confidence)
    workflow.add_node("analyze_root_cause", agents.analyze_root_cause)
    workflow.add_node("decide_escalation", agents.decide_escalation)
    workflow.add_node("persist_response", agents.persist_response)

    # Set entry point
    workflow.set_entry_point("classify_intent")

    # Add edges (flow control)
    workflow.add_edge("classify_intent", "retrieve_documents")
    workflow.add_edge("retrieve_documents", "generate_answer")
    workflow.add_edge("generate_answer", "score_confidence")
    workflow.add_edge("score_confidence", "analyze_root_cause")
    workflow.add_edge("analyze_root_cause", "decide_escalation")
    workflow.add_edge("decide_escalation", "persist_response")
    workflow.add_edge("persist_response", END)

    return workflow.compile()


def execute_query(workflow, state: SupportAgentState) -> SupportAgentState:
    """
    Execute a support query through the multi-agent workflow.

    Args:
        workflow: Compiled StateGraph
        state: Input SupportAgentState

    Returns:
        Completed SupportAgentState with all processing results
    """
    try:
        observability.log_step("workflow.start", "workflow_start=true", request_id=state.request_id)
        final_state = workflow.invoke(state)
        if isinstance(final_state, Mapping):
            final_state = SupportAgentState(**final_state)
        observability.log_step("workflow.complete", "workflow_complete=true", request_id=state.request_id)
        return final_state
    except Exception as e:
        observability.log_step("workflow.error", f"workflow_error={str(e)}", request_id=state.request_id, level=40)
        state.should_escalate = True
        state.escalation_reason = f"Workflow error: {str(e)}"
        return state
