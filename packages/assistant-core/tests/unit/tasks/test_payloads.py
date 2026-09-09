"""What a durable job carries from the deferring turn to the worker."""

from collections.abc import Generator
from contextlib import AbstractAsyncContextManager, nullcontext
from uuid import uuid4

import pytest

from assistant_core.tasks.job_context import (
    DurableJobState,
    durable_job_context,
    install_durable_job_context,
    reset_durable_job_context,
)
from assistant_core.tasks.payloads import DurableTaskPayload


class _CarriedState(DurableJobState):
    """The one value this host carries onto the worker."""

    token: str = ""


class _Carried:
    """A host job context that carries one value."""

    state_type = _CarriedState

    def __init__(self, value: str) -> None:
        self.value = value
        self.restored: list[DurableJobState] = []

    def capture(self) -> _CarriedState:
        return _CarriedState(token=self.value)

    def restore(self, state: DurableJobState) -> AbstractAsyncContextManager[None]:
        self.restored.append(state)
        return nullcontext()


@pytest.fixture
def default_job_context() -> Generator[None]:
    reset_durable_job_context()
    yield
    reset_durable_job_context()


def test_a_payload_carries_nothing_extra_when_no_host_installed_a_context(
    default_job_context: None,
) -> None:
    del default_job_context
    payload = DurableTaskPayload.from_context(
        task_id=uuid4(),
        thread_id=uuid4(),
        args={"kwargs": {"n": 3}},
    )

    assert payload.job_context == DurableJobState()
    assert payload.capture_dir is None
    assert payload.args == {"kwargs": {"n": 3}}


def test_a_payload_carries_what_the_installed_context_captured(
    default_job_context: None,
) -> None:
    del default_job_context
    carried = _Carried("abc123")
    install_durable_job_context(carried)

    payload = DurableTaskPayload.from_context(
        task_id=uuid4(),
        thread_id=uuid4(),
        args={},
    )

    assert payload.job_context == _CarriedState(token="abc123")
    assert payload.model_dump(mode="json")["job_context"] == {"token": "abc123"}


def test_the_payload_dumps_the_kwargs_the_job_is_deferred_with(
    default_job_context: None,
) -> None:
    del default_job_context
    task_id, thread_id = uuid4(), uuid4()

    dumped = DurableTaskPayload.from_context(
        task_id=task_id,
        thread_id=thread_id,
        args={"kwargs": {"n": 3}},
    ).model_dump(mode="json", by_alias=True)

    assert dumped == {
        "task_id": str(task_id),
        "thread_id": str(thread_id),
        "args": {"kwargs": {"n": 3}},
        "capture_dir": None,
        "job_context": {},
    }


async def test_the_default_context_restores_nothing_and_refuses_nothing(
    default_job_context: None,
) -> None:
    del default_job_context
    async with durable_job_context().restore(DurableJobState()):
        pass
