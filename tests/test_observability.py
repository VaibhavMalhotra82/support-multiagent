import importlib
import io
import unittest

from app import observability


class ObservabilityTests(unittest.TestCase):
    def test_log_step_uses_request_context_and_resets(self):
        stream = io.StringIO()
        handler = observability.logger.handlers[0].__class__(stream)
        handler.setFormatter(observability.logger.handlers[0].formatter)
        observability.logger.addHandler(handler)
        context_token = observability.set_request_id("context-request")
        try:
            observability.log_step("test.context", "contextual")
            observability.log_step("test.explicit", "explicit", request_id="explicit-request")
        finally:
            observability.reset_request_id(context_token)
            observability.logger.removeHandler(handler)
            handler.close()

        output = stream.getvalue()
        self.assertIn("step=test.context request_id=context-request contextual", output)
        self.assertIn("step=test.explicit request_id=explicit-request explicit", output)

        stream = io.StringIO()
        handler = observability.logger.handlers[0].__class__(stream)
        handler.setFormatter(observability.logger.handlers[0].formatter)
        observability.logger.addHandler(handler)
        try:
            observability.log_step("test.after_context", "background")
        finally:
            observability.logger.removeHandler(handler)
            handler.close()

        self.assertIn("step=test.after_context request_id=- background", stream.getvalue())

    def test_structured_log_contains_operational_context(self):
        stream = io.StringIO()
        handler = observability.logger.handlers[0].__class__(stream)
        handler.setFormatter(observability.logger.handlers[0].formatter)
        observability.logger.addHandler(handler)
        try:
            observability.log_step("test.step", "completed", request_id="request-1")
        finally:
            observability.logger.removeHandler(handler)
            handler.close()

        output = stream.getvalue()
        self.assertIn("file=test_observability.py", output)
        self.assertIn("step=test.step", output)
        self.assertIn("request_id=request-1", output)
        self.assertIn("completed", output)

    def test_reload_does_not_duplicate_configured_handler(self):
        importlib.reload(observability)
        configured = [
            handler for handler in observability.logger.handlers
            if getattr(handler, "_support_multiagent_handler", False)
        ]
        self.assertEqual(len(configured), 1)

    def test_request_and_response_logs_include_payloads_without_secrets(self):
        stream = io.StringIO()
        handler = observability.logger.handlers[0].__class__(stream)
        handler.setFormatter(observability.logger.handlers[0].formatter)
        observability.logger.addHandler(handler)
        try:
            observability.log_request(
                "request-2",
                {"question": "Installation", "authorization": "secret-token"},
            )
            observability.log_response(
                "request-2",
                {"answer": "Use pip", "request_id": "request-2"},
            )
        finally:
            observability.logger.removeHandler(handler)
            handler.close()

        output = stream.getvalue()
        self.assertIn('request={"authorization": "[REDACTED]", "question": "Installation"}', output)
        self.assertIn('response={"answer": "Use pip", "request_id": "request-2"}', output)
        self.assertNotIn("secret-token", output)


if __name__ == "__main__":
    unittest.main()
