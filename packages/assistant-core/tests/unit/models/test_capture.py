from __future__ import annotations

import json
from itertools import count
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

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
