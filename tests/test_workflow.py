import unittest
from unittest.mock import patch

from app import cache
from app.contracts.state import SupportAgentState
from app.knowledge import retrieval
from app.workflow import agents
from app.workflow.langgraph import execute_query


class WorkflowRegressionTests(unittest.TestCase):
    def test_workflow_result_is_normalized_to_state_dataclass(self):
        state = SupportAgentState(question="installation help", session_id="session-1")
        workflow_result = {
            "question": state.question,
            "session_id": state.session_id,
            "should_escalate": True,
            "escalation_reason": "low confidence",
        }

        result = execute_query(_MappingWorkflow(workflow_result), state)

        self.assertIsInstance(result, SupportAgentState)
        self.assertTrue(result.should_escalate)
        self.assertEqual(result.escalation_reason, "low confidence")

    def test_retrieval_and_workflow_use_shared_cache(self):
        self.assertIs(cache.cache, retrieval.cache)

        state = SupportAgentState(
            question="installation help",
            session_id="session-1",
            metadata={},
        )
        key = cache.CacheKey.build("retrieval", state.question, state.metadata)
        cache.cache.set(key, '[{"text": "cached answer"}]', ttl=300)
        try:
            result = agents.retrieve_documents(state)
        finally:
            cache.cache.delete(key)

        self.assertTrue(result.retrieval_cache_hit)
        self.assertEqual(result.retrieved_documents, [{"text": "cached answer"}])

    def test_llm_call_logs_usage_and_latency(self):
        class _Response:
            content = "answer"
            usage_metadata = {
                "input_tokens": 12,
                "output_tokens": 7,
                "total_tokens": 19,
            }
            response_metadata = {"model_name": "test-model"}

        class _LLM:
            model_name = "fallback-model"

            def invoke(self, messages):
                return _Response()

        state = SupportAgentState(question="installation help", session_id="session-1")
        with patch.object(agents, "llm", _LLM()), patch.object(agents.observability, "log_step") as log_step:
            result = agents._invoke_llm([], state, "generate_answer")

        self.assertEqual(result.content, "answer")
        message = log_step.call_args.args[1]
        self.assertIn("model=test-model", message)
        self.assertIn("input_tokens=12", message)
        self.assertIn("output_tokens=7", message)
        self.assertIn("total_tokens=19", message)
        self.assertIn("latency_ms=", message)


class _MappingWorkflow:
    def __init__(self, result):
        self.result = result

    def invoke(self, state):
        return self.result


if __name__ == "__main__":
    unittest.main()
