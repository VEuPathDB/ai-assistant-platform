"""What ``setup_logging`` leaves behind on the standard-library loggers."""

from __future__ import annotations

import logging
from collections.abc import Generator

import pytest

from assistant_core.platform.logging import (
    QUIET_LOGGERS,
    UVICORN_LOGGERS,
    setup_logging,
)


@pytest.fixture
def restore_logging() -> Generator[None]:
    """Give the process back every logger attribute ``setup_logging`` writes."""
    root = logging.getLogger()
    saved_root = (list(root.handlers), root.level)
    saved_named = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in (*UVICORN_LOGGERS, *QUIET_LOGGERS)
    }
    yield
    root.handlers = saved_root[0]
    root.setLevel(saved_root[1])
    for name, (handlers, level, propagate) in saved_named.items():
        named = logging.getLogger(name)
        named.handlers = handlers
        named.setLevel(level)
        named.propagate = propagate


def test_a_second_call_leaves_one_root_handler(restore_logging: None) -> None:
    """A process that configures logging twice must not log every line twice."""
    del restore_logging
    setup_logging()
    setup_logging()

    assert len(logging.getLogger().handlers) == 1


def test_the_served_loggers_reach_the_root_handler(restore_logging: None) -> None:
    """uvicorn ships with propagation off, so its request lines need it on."""
    del restore_logging
    setup_logging()

    for name in UVICORN_LOGGERS:
        served = logging.getLogger(name)
        assert served.propagate is True
        assert served.handlers == []
        assert served.level == logging.INFO
