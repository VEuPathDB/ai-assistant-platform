"""A run reads each section as the run found it, and a section a tool call
changed reaches the model after that call's result, so every request of the
run extends the one before it."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturn,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage

from assistant_core.capabilities.stable_instructions import (
    SECTION_UPDATE_LEAD,
    StableInstructions,
    briefing_now,
)


@dataclass
class _Board:
    """State a tool changes and a section renders."""

    stage: str = "planned"
    rules: str = "Answer in one line."
    gone: bool = False
    seen: list[tuple[str, list[ModelMessage]]] = field(default_factory=list)


def _stage(ctx: RunContext[_Board]) -> str:
    return f"## Stage\n{ctx.deps.stage}"


def _rules(ctx: RunContext[_Board]) -> str:
    return f"## Rules\n{ctx.deps.rules}"


def _fading(ctx: RunContext[_Board]) -> str | None:
    return None if ctx.deps.gone else "## Draft\nopen"


def _agent(board: _Board, *, calls: int = 1) -> Agent[_Board, str]:
    def _model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        request = messages[-1]
        assert isinstance(request, ModelRequest)
        board.seen.append((request.instructions or "", list(messages)))
        if len(board.seen) <= calls:
            return ModelResponse(parts=[ToolCallPart("advance", {})])
        return ModelResponse(parts=[TextPart("done")])

    stable = StableInstructions[_Board]()
    agent: Agent[_Board, str] = Agent(
        FunctionModel(_model), deps_type=_Board, capabilities=[stable]
    )
    for render in (_rules, _stage, _fading):
        agent.instructions(stable.section(render))

    @agent.tool
    def advance(ctx: RunContext[_Board]) -> str:
        """Move the board on."""
        ctx.deps.stage = "built"
        ctx.deps.gone = True
        return "moved"

    return agent


def _update_items(message: ModelMessage) -> list[object]:
    assert isinstance(message, ModelRequest)
    return [part.content for part in message.parts if isinstance(part, UserPromptPart)]


async def test_every_request_of_a_run_reads_the_same_instructions() -> None:
    board = _Board()

    await _agent(board).run("go", deps=board)

    first, second = (instructions for instructions, _ in board.seen)
    assert first == second
    assert "## Stage\nplanned" in first


async def test_a_changed_section_follows_the_result_of_the_call_that_changed_it() -> (
    None
):
    board = _Board()

    await _agent(board).run("go", deps=board)

    _, messages = board.seen[1]
    assert _update_items(messages[-1]) == [
        [
            SECTION_UPDATE_LEAD,
            "## Stage\nbuilt",
            "The section ## Draft no longer applies.",
        ]
    ]


async def test_each_request_extends_the_one_before_it() -> None:
    board = _Board()

    await _agent(board, calls=2).run("go", deps=board)

    (_, first), (_, second), (_, third) = board.seen
    assert second[: len(first)] == first
    assert third[: len(second)] == second


async def test_a_section_no_call_changed_is_not_sent_again() -> None:
    board = _Board()

    await _agent(board, calls=2).run("go", deps=board)

    _, messages = board.seen[2]
    assert _update_items(messages[-1]) == []


async def test_a_new_run_reads_the_sections_as_they_stand() -> None:
    board = _Board()
    agent = _agent(board)
    await agent.run("go", deps=board)
    board.seen.clear()

    await agent.run("again", deps=board)

    assert "## Stage\nbuilt" in board.seen[0][0]


def _no_reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart("unused")])


async def test_a_section_outside_a_run_renders_as_it_stands() -> None:
    board = _Board(stage="built")
    stable = StableInstructions[_Board]()
    ctx = RunContext(deps=board, model=FunctionModel(_no_reply), usage=RunUsage())

    assert await stable.section(_stage)(ctx) == "## Stage\nbuilt"


async def test_a_tool_that_sends_its_own_content_keeps_it_before_the_update() -> None:
    board = _Board()
    stable = StableInstructions[_Board]()

    def _model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        board.seen.append(("", list(messages)))
        if len(board.seen) == 1:
            return ModelResponse(parts=[ToolCallPart("advance", {})])
        return ModelResponse(parts=[TextPart("done")])

    agent: Agent[_Board, str] = Agent(
        FunctionModel(_model), deps_type=_Board, capabilities=[stable]
    )
    agent.instructions(stable.section(_stage))

    @agent.tool
    def advance(ctx: RunContext[_Board]) -> ToolReturn[str]:
        """Move the board on, with a note of its own."""
        ctx.deps.stage = "built"
        return ToolReturn(return_value="moved", content="the step was pushed")

    await agent.run("go", deps=board)

    request = board.seen[1][1][-1]
    assert isinstance(request, ModelRequest)
    assert [p.content for p in request.parts if isinstance(p, UserPromptPart)] == [
        ["the step was pushed", SECTION_UPDATE_LEAD, "## Stage\nbuilt"]
    ]


_PINNED = (
    "You plan searches.\n\n## Stage\nplanned\n\n# Ledger\n## Frame\nopen\n\n"
    "## Notes (0 notes)\nnone"
)


def test_the_briefing_now_reads_each_updated_section_in_its_place() -> None:
    updates = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    content=[
                        SECTION_UPDATE_LEAD,
                        "# Ledger\n## Frame\nbound",
                        "## Notes (1 notes)\nkept",
                    ]
                )
            ]
        )
    ]

    assert briefing_now(_PINNED, updates) == (
        "You plan searches.\n\n## Stage\nplanned\n\n# Ledger\n## Frame\nbound\n\n"
        "## Notes (1 notes)\nkept"
    )


def test_a_section_that_no_longer_applies_leaves_the_briefing() -> None:
    updates = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    content=[
                        SECTION_UPDATE_LEAD,
                        "The section ## Stage no longer applies.",
                    ]
                )
            ]
        )
    ]

    assert "## Stage" not in briefing_now(_PINNED, updates)


def test_a_section_the_run_began_without_joins_the_end_of_the_briefing() -> None:
    updates = [
        ModelRequest(
            parts=[UserPromptPart(content=[SECTION_UPDATE_LEAD, "## Draft\nopen"])]
        )
    ]

    assert briefing_now(_PINNED, updates).endswith(
        "## Notes (0 notes)\nnone\n\n## Draft\nopen"
    )
