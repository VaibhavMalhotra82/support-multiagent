import json
import logging
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("support_multiagent")
_request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
logger.propagate = False
if not any(getattr(existing, "_support_multiagent_handler", False) for existing in logger.handlers):
    handler = logging.StreamHandler()
    handler._support_multiagent_handler = True
    formatter = logging.Formatter(
        "%(asctime)s level=%(levelname)s file=%(filename)s line=%(lineno)d "
        "process=%(processName)s/%(process)d step=%(step)s request_id=%(request_id)s %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class _ContextDefaults(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "step"):
            record.step = "general"
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


for configured_handler in logger.handlers:
    if not any(isinstance(existing_filter, _ContextDefaults) for existing_filter in configured_handler.filters):
        configured_handler.addFilter(_ContextDefaults())


def set_request_id(request_id: str) -> object:
    return _request_id_context.set(request_id)


def reset_request_id(token: object) -> None:
    _request_id_context.reset(token)


def get_request_id() -> str | None:
    return _request_id_context.get()


def log_step(
    step: str,
    message: str,
    *,
    request_id: str | None = None,
    level: int = logging.INFO,
    stacklevel: int = 2,
) -> None:
    resolved_request_id = request_id or get_request_id() or "-"
    logger.log(
        level,
        message,
        extra={"step": step, "request_id": resolved_request_id},
        stacklevel=stacklevel,
    )


_SENSITIVE_FIELDS = {"api_key", "authorization", "password", "token", "access_token"}


def _safe_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: "[REDACTED]" if key.lower() in _SENSITIVE_FIELDS else _safe_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [_safe_payload(value) for value in payload]
    return payload


def _serialize_payload(payload: Any) -> str:
    return json.dumps(_safe_payload(payload), default=str, ensure_ascii=True, sort_keys=True)


def log_request(request_id: str, payload: dict) -> None:
    log_step("query.request", f"request={_serialize_payload(payload)}", request_id=request_id, stacklevel=3)


def log_response(request_id: str, response: dict) -> None:
    log_step("query.response", f"response={_serialize_payload(response)}", request_id=request_id, stacklevel=3)


def log_auth(user: str, action: str, success: bool) -> None:
    log_step("auth", f"user={user} action={action} success={success}", stacklevel=3)
