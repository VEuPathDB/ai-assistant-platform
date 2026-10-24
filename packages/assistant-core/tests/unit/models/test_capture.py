from __future__ import annotations

import json
from itertools import count
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.test import TestModel

from assistant_core.capabilities.allowed_tools import AllowedTools
from assistant_core.models.capture import (
    CapturingModel,
    capture_llm,
    maybe_wrap_model,
)


@pytest.mark.asyncio
async def test_captures_request_and_response_nonstreaming(tmp_path: Path) -> None:
    cap = CapturingModel(TestModel(), run_dir=tmp_path, role="review", seq=count(1))
    agent = Agent(cap, system_prompt="You are a review agent. Follow the rules.")
    await agent.run("check the rows")

    files = sorted((tmp_path / "llm").glob("*.json"))
    names = [f.name for f in files]
    assert any("request" in n for n in names)
    assert any("response" in n for n in names)

    req = json.loads(next(f for f in files if "request" in f.name).read_text())
    assert req["role"] == "review"
    # the system prompt the model actually received is in the captured messages
    assert "review agent" in json.dumps(req["messages"]).lower()


@pytest.mark.asyncio
async def test_captures_streaming_path(tmp_path: Path) -> None:
    cap = CapturingModel(TestModel(), run_dir=tmp_path, role="review", seq=count(1))
    agent = Agent(cap, system_prompt="stream rules here")
    async with agent.run_stream("go") as result:
        await result.get_output()

    files = sorted((tmp_path / "llm").glob("*.json"))
    assert any("request" in f.name for f in files)
    assert any("response" in f.name for f in files)


def test_capture_llm_hook_wraps_models_only_inside_block(tmp_path: Path) -> None:
    with capture_llm(tmp_path):
        wrapped = maybe_wrap_model(TestModel(), "drafting")
        assert isinstance(wrapped, CapturingModel)
        assert wrapped._role == "drafting"
    passthrough = maybe_wrap_model("openai:gpt-4.1", "drafting")
    assert passthrough == "openai:gpt-4.1"


@pytest.mark.asyncio
async def test_a_tool_choice_in_the_settings_is_captured(tmp_path: Path) -> None:
    cap = CapturingModel(
        TestModel(call_tools=["read"]), run_dir=tmp_path, role="lead", seq=count(1)
    )
    agent = Agent(
        cap, capabilities=[AllowedTools[None](rules=[lambda ctx, names: {"build"}])]
    )

    @agent.tool_plain
    def read() -> str:
        """Read the strategy."""
        return "read"

    @agent.tool_plain
    def build() -> str:
        """Build the strategy."""
        return "built"

    await agent.run("go")

    request = next(
        f for f in sorted((tmp_path / "llm").glob("*.json")) if "request" in f.name
    )
    assert json.loads(request.read_text())["settings"]["tool_choice"] == {
        "function_tools": ["read"]
    }


class _Reading(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    gene_count: int = Field(alias="geneCount")
    record_type: str = Field(alias="recordType")


@pytest.mark.asyncio
async def test_a_captured_tool_return_has_the_keys_the_model_reads(
    tmp_path: Path,
) -> None:
    cap = CapturingModel(
        TestModel(call_tools=["read"]), run_dir=tmp_path, role="lead", seq=count(1)
    )
    agent = Agent(cap)

    @agent.tool_plain
    def read() -> _Reading:
        """Read the strategy."""
        return _Reading(gene_count=3, record_type="transcript")

    result = await agent.run("go")

    sent = [
        part.model_response_object()
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    requests = [
        json.loads(f.read_text())
        for f in sorted((tmp_path / "llm").glob("*.json"))
        if "request" in f.name
    ]
    captured = [
        part["content"]
        for message in requests[-1]["messages"]
        for part in message["parts"]
        if part["part_kind"] == "tool-return"
    ]
    assert sent == [{"geneCount": 3, "recordType": "transcript"}]
    assert captured == sent
