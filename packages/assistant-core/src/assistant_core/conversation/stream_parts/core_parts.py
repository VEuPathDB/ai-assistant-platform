"""Stream parts of the assistant runtime: tasks, usage, turn state, consults."""

from assistant_core.conversation.stream_parts.registry import (
    StreamPartRegistry,
)
from assistant_core.conversation.stream_parts.task_parts import (
    BackgroundTaskStarted,
    TaskCompleted,
    TaskProgress,
)
from assistant_core.conversation.stream_parts.turn_usage import TurnUsage
from assistant_core.graph.stream_events import (
    ConversationTitlePayload,
    LeadUsagePayload,
    SubAgentCallPayload,
    SubAgentStepPayload,
    ToolSummaryPayload,
    TurnFailedPayload,
    TurnStatusPayload,
    TurnStoppedPayload,
)
from assistant_core.graph.turn_state import (
    ConsultQuestion,
    UserQuestionAnswer,
)


def register_core_stream_parts(registry: StreamPartRegistry) -> None:
    registry.register("data-background-task-started", BackgroundTaskStarted)
    registry.register("data-task-progress", TaskProgress)
    registry.register("data-task-completed", TaskCompleted)
    registry.register("data-turn-usage", TurnUsage)
    registry.register("data-lead-usage", LeadUsagePayload)
    registry.register("data-turn-status", TurnStatusPayload)
    registry.register("data-turn-stopped", TurnStoppedPayload)
    registry.register("data-turn-failed", TurnFailedPayload)
    registry.register("data-sub-agent-call", SubAgentCallPayload)
    registry.register("data-sub-agent-step", SubAgentStepPayload)
    registry.register("data-conversation-title", ConversationTitlePayload)
    registry.register("data-tool-summary", ToolSummaryPayload)
    registry.register_schema_only("consult_question", ConsultQuestion)
    registry.register_schema_only("user_question_answer", UserQuestionAnswer)


STREAM_PARTS = StreamPartRegistry()
"""The process-wide registry. Each product registers its own parts onto it."""

register_core_stream_parts(STREAM_PARTS)
