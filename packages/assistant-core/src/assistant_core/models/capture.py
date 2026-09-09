from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from itertools import count
from pathlib import Path
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
)
from pydantic_ai.models import (
    Model,
    ModelRequestParameters,
    StreamedResponse,
    infer_model,
)
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

LLMCaptureHook = Callable[[Model | str, str], Model]

_llm_capture_hook: ContextVar[LLMCaptureHook | None] = ContextVar(
    "llm_capture_hook", default=None
)
_current_capture_dir: ContextVar[str | None] = ContextVar(
    "current_capture_dir", default=None
)


def set_llm_capture_hook(hook: LLMCaptureHook | None) -> Token[LLMCaptureHook | None]:
    """Install a per-call model-wrapping hook. Returns the token to reset with.

    An unset hook costs nothing at the model-override sites.
    """
    return _llm_capture_hook.set(hook)


def reset_llm_capture_hook(token: Token[LLMCaptureHook | None]) -> None:
    _llm_capture_hook.reset(token)


def current_capture_dir() -> str | None:
    """The active LLM-capture run directory, if any.

    A deferred call reads it to carry capture into the job that answers it.
    """
    return _current_capture_dir.get()


def maybe_wrap_model(model: Model | str, role: str) -> Model | str:
    """Wrap the model resolved for a role when a capture hook is active.

    Without a hook the model is returned untouched.
    """
    hook = _llm_capture_hook.get()
    if hook is None:
        return model
    return hook(model, role)


def _dump(messages: list[ModelMessage]) -> Any:
    return json.loads(ModelMessagesTypeAdapter.dump_json(messages))


def _tool_defs(params: ModelRequestParameters) -> list[dict[str, Any]]:
    return [
        {
            "name": td.name,
            "description": td.description,
            "parameters": td.parameters_json_schema,
        }
        for td in params.function_tools
    ]


class CapturingModel(WrapperModel):
    """Records every request and response of the model it wraps, untruncated,
    under ``<run-dir>/llm/``. A file name carries the instant, so the captures
    of several jobs share one ordered directory."""

    def __init__(
        self, wrapped: Model | str, *, run_dir: Path, role: str, seq: Iterator[int]
    ) -> None:
        super().__init__(infer_model(wrapped))
        self._dir = Path(run_dir) / "llm"
        self._role = role
        self._seq = seq

    def _stem(self) -> str:
        return f"{time.time_ns()}-{next(self._seq):04d}-{self._role}"

    def _write_request(
        self,
        stem: str,
        messages: list[ModelMessage],
        settings: ModelSettings | None,
        params: ModelRequestParameters,
    ) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "role": self._role,
            "model": f"{self.wrapped.system}:{self.wrapped.model_name}",
            "settings": dict(settings) if settings else {},
            "tools": _tool_defs(params),
            "allow_text_output": params.allow_text_output,
            "messages": _dump(messages),
        }
        (self._dir / f"{stem}-request.json").write_text(json.dumps(payload, indent=2))

    def _write_response(self, stem: str, response: ModelResponse) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        dumped = _dump([response])[0]
        payload = {
            "role": self._role,
            "model": f"{self.wrapped.system}:{self.wrapped.model_name}",
            "finishReason": response.finish_reason,
            "usage": dumped.get("usage"),
            "response": dumped,
        }
        (self._dir / f"{stem}-response.json").write_text(json.dumps(payload, indent=2))

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        stem = self._stem()
        self._write_request(stem, messages, model_settings, model_request_parameters)
        response = await super().request(
            messages, model_settings, model_request_parameters
        )
        self._write_response(stem, response)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        stem = self._stem()
        self._write_request(stem, messages, model_settings, model_request_parameters)
        async with super().request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            yield stream
        self._write_response(stem, stream.get())


@contextmanager
def capture_llm(run_dir: Path | str) -> Iterator[None]:
    """Install the capture hook for the block and publish the run directory.

    Every role's resolved model is wrapped, so each call lands in
    ``<run-dir>/llm/``.
    """

    seq = count(1)
    run_dir = Path(run_dir)

    def _wrap(model: Model | str, role: str) -> Model:
        return CapturingModel(model, run_dir=run_dir, role=role, seq=seq)

    hook_token = set_llm_capture_hook(_wrap)
    dir_token = _current_capture_dir.set(str(run_dir))
    try:
        yield
    finally:
        reset_llm_capture_hook(hook_token)
        _current_capture_dir.reset(dir_token)
