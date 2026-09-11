"""A credential a host carries onto the worker, and what a log may show of it."""

import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from uuid import uuid4

import pytest
from procrastinate.jobs import Job, Status
from pydantic import SecretStr

from assistant_core.tasks.job_context import (
    CarriedSecret,
    DurableJobState,
    install_durable_job_context,
    reset_durable_job_context,
)
from assistant_core.tasks.payloads import DurableTaskPayload
from assistant_core.tasks.redaction import (
    REDACTION_MARKER,
    RedactJobContextFilter,
    install_job_payload_redaction,
)

TOKEN = "WDK-9f2c4b7e-live-session-cookie"


class _HostState(DurableJobState):
    """A host's carried state, with the credential typed as a secret."""

    auth_token: CarriedSecret | None = None


class _HostContext:
    """A host job context that carries one credential onto the worker."""

    state_type = _HostState

    def __init__(self) -> None:
        self.read_back: list[str] = []

    def capture(self) -> _HostState:
        return _HostState(auth_token=SecretStr(TOKEN))

    def restore(self, state: DurableJobState) -> AbstractAsyncContextManager[None]:
        read_back = self.read_back

        @asynccontextmanager
        async def _scope() -> AsyncIterator[None]:
            carried = _HostState.model_validate(state.model_dump())
            if carried.auth_token is not None:
                # The point of use is the only place the value is readable.
                read_back.append(carried.auth_token.get_secret_value())
            yield

        return _scope()


@pytest.fixture
def host_context() -> AsyncIterator[_HostContext]:
    context = _HostContext()
    install_durable_job_context(context)
    yield context
    reset_durable_job_context()


def _payload(host_context: _HostContext) -> DurableTaskPayload:
    del host_context
    return DurableTaskPayload.from_context(
        task_id=uuid4(),
        thread_id=uuid4(),
        args={"kwargs": {"n": 2}},
    )


def test_the_captured_state_masks_its_secret_in_repr_and_str(
    host_context: _HostContext,
) -> None:
    payload = _payload(host_context)

    assert TOKEN not in repr(payload)
    assert TOKEN not in str(payload)
    assert TOKEN not in repr(payload.job_context)
    assert TOKEN not in str(payload.job_context)
    assert "**********" in repr(payload.job_context)


def test_the_secret_reaches_the_worker_and_reads_back_only_at_the_point_of_use(
    host_context: _HostContext,
) -> None:
    payload = _payload(host_context)

    carried = payload.model_dump(mode="json", by_alias=True)["job_context"]

    assert carried == {"auth_token": TOKEN}


async def test_restoring_the_state_hands_the_body_the_secret(
    host_context: _HostContext,
) -> None:
    state = _HostState.model_validate({"auth_token": TOKEN})

    async with host_context.restore(state):
        pass

    assert host_context.read_back == [TOKEN]


def test_the_job_line_procrastinate_formats_carries_no_token_bytes(
    host_context: _HostContext,
) -> None:
    payload = _payload(host_context)
    job = Job(
        id=41,
        status=Status.DOING.value,
        queue="durable",
        lock=str(uuid4()),
        queueing_lock=None,
        task_name="durable:crunch",
        task_kwargs=payload.model_dump(mode="json", by_alias=True),
    )
    record = logging.LogRecord(
        name="procrastinate.worker.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f"Starting job {job.call_string}",
        args=(),
        exc_info=None,
    )

    assert TOKEN in record.getMessage()
    assert RedactJobContextFilter().filter(record) is True
    assert TOKEN not in record.getMessage()
    assert f"job_context={REDACTION_MARKER}" in record.getMessage()
    assert "durable:crunch[41]" in record.getMessage()
    assert "task_id=" in record.getMessage()


def test_the_filter_scrubs_the_nested_and_quoted_forms_of_the_key() -> None:
    nested = (
        "Starting job durable:crunch[7](task_id='1', "
        "job_context={'auth_token': 'WDK-abc', 'nested': {'k': 'v}'}}, "
        "capture_dir=None)"
    )
    record = logging.LogRecord(
        name="procrastinate",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=nested,
        args=(),
        exc_info=None,
    )

    RedactJobContextFilter().filter(record)

    assert record.getMessage() == (
        "Starting job durable:crunch[7](task_id='1', "
        f"job_context={REDACTION_MARKER}, "
        "capture_dir=None)"
    )


def test_the_filter_scrubs_the_dict_form_a_log_context_renders() -> None:
    record = logging.LogRecord(
        name="procrastinate",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="job={'task_kwargs': {'job_context': {'auth_token': 'WDK-abc'}}}",
        args=(),
        exc_info=None,
    )

    RedactJobContextFilter().filter(record)

    assert "WDK-abc" not in record.getMessage()
    assert f"'job_context': {REDACTION_MARKER}" in record.getMessage()


def test_installing_the_redaction_twice_leaves_one_filter_per_logger() -> None:
    logging.getLogger("procrastinate.worker")
    install_job_payload_redaction()
    install_job_payload_redaction()

    attached = [
        f
        for f in logging.getLogger("procrastinate.worker").filters
        if isinstance(f, RedactJobContextFilter)
    ]

    assert len(attached) == 1
