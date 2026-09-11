"""What each installed seam says when a host installed none, and its reset."""

from contextlib import AbstractAsyncContextManager, nullcontext

import procrastinate
import pytest
from procrastinate.testing import InMemoryConnector

from assistant_core.graph.durable import DURABLE_TOOLS
from assistant_core.graph.runtime import TurnContext
from assistant_core.tasks import names
from assistant_core.tasks.app import (
    TaskAppNotInstalledError,
    durable_task_queue,
    install_task_app,
    reset_task_app,
    task_app,
    worker_queues,
)
from assistant_core.tasks.completion_turn import (
    CompletionTurn,
    CompletionTurnNotInstalledError,
    install_completion_turn,
    installed_completion_turn,
    reset_completion_turn,
)
from assistant_core.tasks.declaration import (
    declare_durable_tool,
    declared_durable_tools,
    empty_durable_tools,
)
from assistant_core.tasks.job_context import (
    DurableJobState,
    durable_job_context,
    install_durable_job_context,
    reset_durable_job_context,
)
from assistant_core.tasks.names import (
    CHAT_TURN_QUEUE,
    DEFAULT_DURABLE_TASK_QUEUE,
    DEFAULT_QUEUE,
    MAINTENANCE_QUEUE,
)
from assistant_core.tasks.runner import (
    WorkerContextNotInstalledError,
    WorkerContextRequest,
    install_worker_context,
    installed_worker_context,
    reset_worker_context,
)


class _CountingContext:
    """A job context that records how often a process captured from it."""

    state_type = DurableJobState

    def __init__(self) -> None:
        self.captures = 0

    def capture(self) -> DurableJobState:
        self.captures += 1
        return DurableJobState()

    def restore(self, state: DurableJobState) -> AbstractAsyncContextManager[None]:
        del state
        return nullcontext()


def test_reaching_the_queue_before_a_host_installs_one_says_what_to_call() -> None:
    reset_task_app()

    with pytest.raises(TaskAppNotInstalledError) as caught:
        task_app()

    assert str(caught.value) == (
        "no task queue is installed: call install_task_app(app) with the "
        "procrastinate application this process opened"
    )


def test_the_installed_application_is_the_one_the_runtime_defers_onto() -> None:
    app = procrastinate.App(connector=InMemoryConnector())
    install_task_app(app)
    try:
        assert task_app() is app
    finally:
        reset_task_app()

    with pytest.raises(TaskAppNotInstalledError):
        task_app()


def test_a_finished_task_without_a_turn_driver_says_what_to_call() -> None:
    reset_completion_turn()

    with pytest.raises(CompletionTurnNotInstalledError) as caught:
        installed_completion_turn()

    assert str(caught.value) == (
        "no completion turn is installed: call install_completion_turn(run) "
        "with the host's turn driver"
    )


def test_the_installed_turn_driver_is_the_one_a_finished_task_opens() -> None:
    opened: list[CompletionTurn] = []

    async def driver(turn: CompletionTurn) -> None:
        opened.append(turn)

    install_completion_turn(driver)

    assert installed_completion_turn() is driver

    reset_completion_turn()
    with pytest.raises(CompletionTurnNotInstalledError):
        installed_completion_turn()
    assert opened == []


def test_a_durable_body_without_a_worker_context_says_what_to_call() -> None:
    reset_worker_context()

    with pytest.raises(WorkerContextNotInstalledError) as caught:
        installed_worker_context()

    assert str(caught.value) == (
        "no worker context is installed: call "
        "install_worker_context(build) with the host's context factory"
    )


def test_the_installed_worker_context_is_the_one_a_body_reads() -> None:
    async def build(request: WorkerContextRequest) -> TurnContext:
        raise NotImplementedError(str(request.task_id))

    install_worker_context(build)

    assert installed_worker_context() is build

    reset_worker_context()
    with pytest.raises(WorkerContextNotInstalledError):
        installed_worker_context()


def test_the_default_job_context_comes_back_with_its_reset() -> None:
    carried = _CountingContext()
    install_durable_job_context(carried)

    assert durable_job_context() is carried

    reset_durable_job_context()

    assert durable_job_context().capture() == DurableJobState()
    assert durable_job_context().state_type is DurableJobState
    assert carried.captures == 0


def test_the_declaration_registry_empties_and_comes_back() -> None:
    with empty_durable_tools():
        outer = declare_durable_tool(
            tool_name="outer_tool",
            estimated_duration_seconds=30,
        )
        with empty_durable_tools():
            assert declared_durable_tools() == ()
            assert DURABLE_TOOLS == {}
            inner = declare_durable_tool(
                tool_name="inner_tool",
                estimated_duration_seconds=5,
            )
            assert declared_durable_tools() == (inner,)

        assert declared_durable_tools() == (outer,)
        assert "inner_tool" not in DURABLE_TOOLS


def test_a_host_that_names_no_queue_defers_onto_the_default() -> None:
    reset_task_app()

    assert durable_task_queue() == DEFAULT_DURABLE_TASK_QUEUE
    assert worker_queues() == (
        CHAT_TURN_QUEUE,
        DEFAULT_QUEUE,
        MAINTENANCE_QUEUE,
        DEFAULT_DURABLE_TASK_QUEUE,
    )


def test_the_host_names_the_queue_its_durable_work_runs_on() -> None:
    app = procrastinate.App(connector=InMemoryConnector())
    install_task_app(app, durable_queue="long_running")
    try:
        assert durable_task_queue() == "long_running"
        assert worker_queues()[-1] == "long_running"
    finally:
        reset_task_app()

    assert durable_task_queue() == DEFAULT_DURABLE_TASK_QUEUE


def test_the_queue_names_a_worker_imported_before_are_gone() -> None:
    """A worker still naming the old tuple fails at import, not at run time."""
    exported = dir(names)

    assert "WORKER_QUEUES" not in exported
    assert "DURABLE_TASK_QUEUE" not in exported
