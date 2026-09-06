"""The turn state any assistant carries: the user's message, the turn's
accounting, and the deferred call the turn parked for a user or a worker."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from pydantic_ai.ui.vercel_ai.request_types import (
    TextUIPart,
    ToolApprovalResponded,
)

from assistant_core.memory.schemas import MemoryValue
from assistant_core.platform.pydantic_base import CamelModel


class SubAgentApprovalCall(CamelModel):
    """One approval-required tool call a sub-agent stopped at."""

    tool_call_id: str
    tool_name: str
    args: dict[str, JsonValue] = Field(default_factory=dict)


class SubAgentApprovalPending(CamelModel):
    """A sub-agent run suspended on approvals, with the history that resumes it."""

    role: str
    approvals: list[SubAgentApprovalCall] = Field(default_factory=list)
    messages_json: str = ""


class ParkedCall(CamelModel):
    """One deferred tool call a turn parked, with the history that resumes it.

    A parked call is answered by the user, when it needs an approval, or by
    the worker, when it is a durable task.
    """

    phase: str
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, JsonValue] = Field(default_factory=dict)
    prior_messages_json: str = ""
    # Set when the parked call belongs to a tool inside a sub-agent. The ids
    # above then name the dispatch call, not the tool that was parked.
    sub_agent: SubAgentApprovalPending | None = None


class PendingApproval(ParkedCall):
    # The user message this approval was raised under. Answering the card
    # leaves it unchanged, so a later turn with a different id carries a typed
    # reply rather than an answer.
    user_message_id: UUID | None = None


class DurableCall(CamelModel):
    """One durable tool call a run parked, and the task that answers it."""

    tool_call_id: str
    tool_name: str
    args: dict[str, JsonValue] = Field(default_factory=dict)
    task_id: UUID
    # The name the durable tool registered under, which is not always the name
    # the model called it by.
    durable_tool_name: str


class PendingDurableCall(ParkedCall):
    """The tool calls one model step handed to a worker.

    The run resumes when every task here has reported, because pydantic-ai
    needs a result for each call of the response it re-enters.
    """

    durable_calls: list[DurableCall] = Field(min_length=1)

    @property
    def task_ids(self) -> list[UUID]:
        """Every task the parked run waits on, in call order."""
        return [call.task_id for call in self.durable_calls]

    def owns(self, task_id: UUID) -> bool:
        """Whether one of the parked calls waits on this task."""
        return any(call.task_id == task_id for call in self.durable_calls)


class DurableDeferral(CamelModel):
    """What a durable tool recorded on the deps when it deferred its work."""

    task_id: UUID
    tool_name: str


class DurableTaskResult(CamelModel):
    """The worker's answer to one durable call."""

    task_id: UUID
    status: Literal["success", "failed"]
    result: dict[str, JsonValue] = Field(default_factory=dict)
    error: str = ""

    def as_tool_value(self) -> dict[str, JsonValue]:
        """The value the tool would have returned."""
        if self.status == "failed":
            return {"status": "failed", "error": self.error}
        return {"status": "success", "result": dict(self.result)}


ConsultQuestionKind = Literal["single_choice", "multi_choice", "free_text"]


class ConsultOption(CamelModel):
    """One selectable option on a ``consult_user`` question."""

    label: str
    description: str = ""
    recommended: bool = False


class ConsultQuestion(CamelModel):
    """A design question the assistant asks the user via ``consult_user`` to
    shape the work BEFORE a plan is finalized. Rendered as a carousel slide
    with options + an optional free-text note."""

    id: str
    prompt: str
    kind: ConsultQuestionKind = "single_choice"
    options: list[ConsultOption] = Field(default_factory=list)
    context: str = ""
    allow_notes: bool = True


class UserQuestionAnswer(CamelModel):
    """The user's answer to one ``ConsultQuestion``: chosen option label(s)
    and/or a free-text note. ``chosen_labels`` is empty for free_text."""

    # It is a tool return value, and a tool return reaches the wire through a
    # serializer that names no aliases, so the model names them itself.
    model_config = ConfigDict(serialize_by_alias=True)

    question_id: str
    prompt: str
    chosen_labels: list[str] = Field(default_factory=list)
    note: str = ""


class TurnState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    conversation_id: UUID
    user_id: UUID
    site_id: str
    mode: str

    user_message_id: UUID | None = None
    user_prompt: str = ""
    user_parts: list[TextUIPart] = Field(default_factory=list)
    turn_trace_id: str | None = None
    turn_created_at: str | None = None
    turn_message_id: UUID = Field(default_factory=uuid4)
    turn_start_event_id: int = 0

    turn_total_tokens: int = 0
    turn_total_cost_usd: Decimal = Field(default_factory=lambda: Decimal(0))

    # The thread's own messages, as the last settled turn left them. Serialized
    # with ``ModelMessagesTypeAdapter``; the graph that runs one agent reads it
    # as the run's history.
    thread_messages_json: str = ""

    pending_approval: PendingApproval | None = None
    pending_durable_call: PendingDurableCall | None = None
    # Set only on the turn the worker starts to answer a durable call.
    durable_result: DurableTaskResult | None = None
    # Every parked task's answer, gathered by the worker that opened the turn.
    # A step that parked several calls resumes only when this covers them all.
    durable_results: list[DurableTaskResult] = Field(default_factory=list)
    approval_responses: dict[str, ToolApprovalResponded] = Field(
        default_factory=dict,
    )
    user_question_answers: dict[str, list[UserQuestionAnswer]] = Field(
        default_factory=dict,
    )
    retrieved_memories: list[MemoryValue] = Field(default_factory=list)

    @property
    def durable_answers(self) -> dict[UUID, DurableTaskResult]:
        """The task results this turn carries, by task."""
        answers = {result.task_id: result for result in self.durable_results}
        if self.durable_result is not None:
            answers.setdefault(self.durable_result.task_id, self.durable_result)
        return answers

    @property
    def carries_durable_answer(self) -> bool:
        """Whether this turn brings an answer for a call the thread parked."""
        parked = self.pending_durable_call
        if parked is None:
            return False
        return any(parked.owns(task_id) for task_id in self.durable_answers)

    @property
    def answered_durable_call(self) -> PendingDurableCall | None:
        """The parked durable call every one of whose tasks has reported."""
        parked = self.pending_durable_call
        if parked is None or not self.carries_durable_answer:
            return None
        answers = self.durable_answers
        if any(task_id not in answers for task_id in parked.task_ids):
            return None
        return parked

    @property
    def resumes_parked_call(self) -> bool:
        """Whether this turn re-enters a run the thread parked."""
        return self.pending_approval is not None or self.carries_durable_answer
