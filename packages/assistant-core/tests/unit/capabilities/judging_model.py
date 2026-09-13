"""A model that answers a judge run from a rule, and records what it was asked."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.settings import ModelSettings

from assistant_core.capabilities.injection_judge import InjectionVerdict
from assistant_core.models.scripted import last_user_text

REFUSAL = "the provider refused"

type Answer = Callable[[str], InjectionVerdict]


def always(verdict: InjectionVerdict) -> Answer:
    """One verdict, whatever the text."""

    def _answer(text: str) -> InjectionVerdict:
        del text
        return verdict

    return _answer


def on_marker(marker: str, injected: float, benign: float) -> Answer:
    """An injection exactly when the judged text carries the marker."""

    def _answer(text: str) -> InjectionVerdict:
        found = marker in text
        return InjectionVerdict(
            injection=found,
            confidence=injected if found else benign,
        )

    return _answer


@dataclass
class JudgingModel:
    """Answers every run from ``answer`` and keeps what the agent asked."""

    answer: Answer
    prompts: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    tool_names: list[tuple[str, ...]] = field(default_factory=list)
    message_counts: list[int] = field(default_factory=list)
    settings: list[ModelSettings] = field(default_factory=list)
    _ids: count[int] = field(default_factory=count, init=False)

    @property
    def calls(self) -> int:
        return len(self.prompts)

    def as_model(self) -> FunctionModel:
        def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompt = last_user_text(messages)
            self.prompts.append(prompt)
            self.instructions.append(info.instructions or "")
            self.tool_names.append(tuple(tool.name for tool in info.function_tools))
            self.message_counts.append(len(messages))
            self.settings.append(info.model_settings or ModelSettings())
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=info.output_tools[0].name,
                        args=self.answer(prompt).model_dump(),
                        tool_call_id=f"judge-{next(self._ids)}",
                    ),
                ],
            )

        return FunctionModel(_respond, model_name="test:judge")


class JudgeFailureError(RuntimeError):
    """The model refused the judge's call."""


def failing_model() -> FunctionModel:
    """A model whose every request raises."""

    def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        raise JudgeFailureError(REFUSAL)

    return FunctionModel(_respond, model_name="test:failing")
