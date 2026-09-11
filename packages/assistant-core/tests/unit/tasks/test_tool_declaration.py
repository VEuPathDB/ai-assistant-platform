"""One declaration names a durable tool for the decorator, the job and the worker."""

from typing import Any
from uuid import UUID

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector

from assistant_core.graph.durable import DURABLE_TOOLS
from assistant_core.tasks.app import install_task_app, reset_task_app
from assistant_core.tasks.declaration import (
    DuplicateDurableToolError,
    DurableTool,
    UndeclaredDurableToolError,
    declare_durable_tool,
    declared_durable_tools,
    durable_impl,
    register_durable_impl,
)
from assistant_core.tasks.runner import register_durable_jobs

pytestmark = pytest.mark.usefixtures("empty_registry")


async def _body(**kwargs: Any) -> dict[str, Any]:
    return dict(kwargs)


def test_a_declaration_names_the_job_the_decorator_defers() -> None:
    tool = declare_durable_tool(tool_name="crunch", estimated_duration_seconds=90)

    assert tool.job_name == "durable:crunch"
    assert tool.estimated_duration_seconds == 90


def test_a_declaration_registers_the_spec_the_answering_turn_reads() -> None:
    def chunks(payload: Any, task_id: UUID, call_id: str | None) -> list[Any]:
        del payload, task_id, call_id
        return []

    declare_durable_tool(
        tool_name="crunch",
        estimated_duration_seconds=90,
        chunks_from_result=chunks,
    )

    spec = DURABLE_TOOLS["crunch"]
    assert spec.estimated_duration_seconds == 90
    assert spec.chunks_from_result is chunks


def test_a_second_declaration_of_one_name_is_refused() -> None:
    declare_durable_tool(tool_name="crunch", estimated_duration_seconds=90)

    with pytest.raises(DuplicateDurableToolError) as caught:
        declare_durable_tool(tool_name="crunch", estimated_duration_seconds=10)

    assert str(caught.value) == "durable tool already declared: crunch"


def test_a_body_registered_under_a_declaration_is_the_one_the_worker_finds() -> None:
    tool = declare_durable_tool(tool_name="crunch", estimated_duration_seconds=90)

    register_durable_impl(tool, _body)

    assert durable_impl("crunch") is _body


def test_a_body_registered_under_a_name_nobody_declared_is_refused() -> None:
    declare_durable_tool(tool_name="crunch", estimated_duration_seconds=90)
    typo = DurableTool(tool_name="cruncg", estimated_duration_seconds=90)

    with pytest.raises(UndeclaredDurableToolError) as caught:
        register_durable_impl(typo, _body)

    assert str(caught.value) == (
        "durable tool 'cruncg' is not declared here: pass the value "
        "declare_durable_tool() returned, so the decorator, the job and the "
        "worker share one name; declared: ['crunch']"
    )
    assert durable_impl("cruncg") is None


def test_a_value_that_differs_from_the_declaration_is_refused() -> None:
    """A hand-built copy with another budget is not the declared tool."""
    declare_durable_tool(tool_name="crunch", estimated_duration_seconds=90)
    other = DurableTool(tool_name="crunch", estimated_duration_seconds=5)

    with pytest.raises(UndeclaredDurableToolError):
        register_durable_impl(other, _body)


def test_every_declared_tool_gets_a_job_of_the_matching_name_and_queue() -> None:
    declare_durable_tool(tool_name="crunch", estimated_duration_seconds=90)
    declare_durable_tool(tool_name="sift", estimated_duration_seconds=30)
    app = procrastinate.App(connector=InMemoryConnector())
    install_task_app(app, durable_queue="long_running")
    try:
        register_durable_jobs(app)

        declared = {
            name: task.queue
            for name, task in app.tasks.items()
            if name.startswith("durable:")
        }
        assert declared == {
            "durable:crunch": "long_running",
            "durable:sift": "long_running",
        }
        assert [tool.tool_name for tool in declared_durable_tools()] == [
            "crunch",
            "sift",
        ]
    finally:
        reset_task_app()
