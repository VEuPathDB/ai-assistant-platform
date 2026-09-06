from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from langgraph.errors import GraphBubbleUp
from pydantic_ai.messages import (
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    ThinkingPart,
)
from pydantic_ai.ui.vercel_ai._event_stream import VercelAIEventStream
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage
from pydantic_ai.ui.vercel_ai.response_types import (
    BaseChunk,
    DoneChunk,
    FinishChunk,
    StartChunk,
    ToolApprovalRequestChunk,
    ToolInputAvailableChunk,
    ToolInputDeltaChunk,
    ToolInputErrorChunk,
    ToolInputStartChunk,
    ToolOutputAvailableChunk,
    ToolOutputDeniedChunk,
    ToolOutputErrorChunk,
)

from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)

# TODO(upstream): remove once pydantic-ai exposes
# ``VERCEL_AI_DSP_HEADERS`` from ``pydantic_ai.ui.vercel_ai`` (currently
# only available via the private ``_event_stream`` module).
VERCEL_AI_DSP_HEADERS: dict[str, str] = {
    "x-vercel-ai-ui-message-stream": "v1",
}

_PHASE_STUB_INPUT: SubmitMessage = SubmitMessage(
    trigger="submit-message",
    id="phase",
    messages=[],
)


@dataclass
class PinnedVercelAIEventStream(VercelAIEventStream[Any, Any]):
    # TODO(upstream): file against pydantic-ai. Base class uses a single
    # mutable ``self.message_id`` so an interleaved ``ThinkingPart`` between
    # a TextPart's start and its first delta routes the delta with the
    # wrong id (validator rejects:
    # ``Received reasoning-delta for missing reasoning part with ID ...``).
    # Suggested fix upstream: key id by ``event.index`` instead of
    # ``self.message_id``. Once fixed, delete this class and use
    # ``VercelAIEventStream`` directly in ``PhaseStreamEmitter``.

    _index_to_message_id: dict[int, str] = field(default_factory=dict, init=False)

    async def on_error(
        self,
        error: Exception,
    ) -> AsyncIterator[BaseChunk]:
        # GraphBubbleUp is langgraph control flow; re-raise so Pregel sees it.
        if isinstance(error, GraphBubbleUp):
            raise error
        logger.exception(
            "pydantic-ai stream raised; converting to chat-visible ErrorChunk",
            error_type=type(error).__name__,
            error_msg=str(error),
        )
        async for chunk in super().on_error(error):
            yield chunk

    async def handle_part_start(
        self,
        event: PartStartEvent,
    ) -> AsyncIterator[BaseChunk]:
        async for chunk in super().handle_part_start(event):
            yield chunk
        if isinstance(event.part, (TextPart, ThinkingPart)):
            self._index_to_message_id[event.index] = self.message_id

    async def handle_part_delta(
        self,
        event: PartDeltaEvent,
    ) -> AsyncIterator[BaseChunk]:
        pinned = self._index_to_message_id.get(event.index)
        if pinned is None:
            async for chunk in super().handle_part_delta(event):
                yield chunk
            return
        saved = self.message_id
        self.message_id = pinned
        try:
            async for chunk in super().handle_part_delta(event):
                yield chunk
        finally:
            self.message_id = saved

    async def handle_part_end(
        self,
        event: PartEndEvent,
    ) -> AsyncIterator[BaseChunk]:
        pinned = self._index_to_message_id.get(event.index)
        if pinned is None:
            async for chunk in super().handle_part_end(event):
                yield chunk
            return
        saved = self.message_id
        self.message_id = pinned
        try:
            async for chunk in super().handle_part_end(event):
                yield chunk
        finally:
            self.message_id = saved


_TOOL_OUTPUT_CHUNKS = (
    ToolOutputAvailableChunk,
    ToolOutputErrorChunk,
    ToolOutputDeniedChunk,
    ToolApprovalRequestChunk,
)


@dataclass
class DeferredToolHint:
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]


@dataclass
class PhaseStreamEmitter:
    # Strips turn-level ``StartChunk``/``FinishChunk``/``DoneChunk`` markers
    # so multiple phase runs can be concatenated into one v6 stream.

    message_id: str
    sdk_version: Literal[5, 6] = 6
    deferred_hints: list[DeferredToolHint] = field(default_factory=list)
    _stream: PinnedVercelAIEventStream = field(init=False)
    _started_tool_call_ids: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self._stream = PinnedVercelAIEventStream(
            run_input=_PHASE_STUB_INPUT,
            sdk_version=self.sdk_version,
            server_message_id=self.message_id,
        )
        self._stream.message_id = self.message_id

    async def chunks(
        self,
        events: AsyncIterator[Any],
    ) -> AsyncIterator[BaseChunk]:
        async for chunk in self._stream.transform_stream(events):
            if isinstance(chunk, (StartChunk, FinishChunk, DoneChunk)):
                continue
            for synthetic in self._synthesize_missing_start(chunk):
                yield synthetic
            yield chunk

    def _synthesize_missing_start(
        self,
        chunk: BaseChunk,
    ) -> list[BaseChunk]:
        if isinstance(chunk, ToolInputStartChunk):
            self._started_tool_call_ids.add(chunk.tool_call_id)
            return []
        # ToolInputDeltaChunk / ToolInputAvailableChunk / ToolInputErrorChunk
        # always follow a ToolInputStartChunk emitted by the upstream stream
        # in normal turns; for resume turns where pydantic-ai's CallToolsNode
        # skips part-event replay, the delta/output chunks for the deferred
        # call land first. Backfill the missing start (and an
        # input-available stub) so the browser parser accepts them.
        if isinstance(chunk, _TOOL_OUTPUT_CHUNKS) and not isinstance(
            chunk,
            ToolApprovalRequestChunk,
        ):
            tool_call_id = chunk.tool_call_id
            if tool_call_id in self._started_tool_call_ids:
                return []
            self._started_tool_call_ids.add(tool_call_id)
            hint = next(
                (h for h in self.deferred_hints if h.tool_call_id == tool_call_id),
                None,
            )
            if hint is None:
                return []
            return [
                ToolInputStartChunk(
                    tool_call_id=tool_call_id,
                    tool_name=hint.tool_name,
                ),
                ToolInputAvailableChunk(
                    tool_call_id=tool_call_id,
                    tool_name=hint.tool_name,
                    input=hint.tool_args,
                ),
            ]
        if isinstance(
            chunk,
            (ToolInputDeltaChunk, ToolInputAvailableChunk, ToolInputErrorChunk),
        ):
            self._started_tool_call_ids.add(chunk.tool_call_id)
        return []
