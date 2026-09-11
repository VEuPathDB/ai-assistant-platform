"""The job queue the host opens and the runtime defers onto.

The runtime owns no connection pool and no schema, so the host builds the
procrastinate application and installs it here once per process, with the name
of the queue its durable work runs on.
"""

from __future__ import annotations

import procrastinate

from assistant_core.tasks.names import (
    CHAT_TURN_QUEUE,
    DEFAULT_DURABLE_TASK_QUEUE,
    DEFAULT_QUEUE,
    MAINTENANCE_QUEUE,
)


class TaskAppNotInstalledError(RuntimeError):
    """The runtime was asked to reach the queue before a host installed one."""

    def __init__(self) -> None:
        super().__init__(
            "no task queue is installed: call install_task_app(app) with the "
            "procrastinate application this process opened",
        )


class _TaskApp:
    """The one procrastinate application this process runs on."""

    def __init__(self) -> None:
        self._app: procrastinate.App | None = None
        self._durable_queue = DEFAULT_DURABLE_TASK_QUEUE

    def install(self, app: procrastinate.App, durable_queue: str) -> None:
        self._app = app
        self._durable_queue = durable_queue

    def reset(self) -> None:
        self._app = None
        self._durable_queue = DEFAULT_DURABLE_TASK_QUEUE

    def read(self) -> procrastinate.App:
        if self._app is None:
            raise TaskAppNotInstalledError
        return self._app

    def durable_queue(self) -> str:
        return self._durable_queue


_installed = _TaskApp()


def install_task_app(
    app: procrastinate.App,
    *,
    durable_queue: str = DEFAULT_DURABLE_TASK_QUEUE,
) -> None:
    """Run this process's durable work on the host's application and queue.

    Every process of one deployment names the same queue: a job deferred onto
    one queue is consumed by a worker that subscribes to it and by no other.
    """
    _installed.install(app, durable_queue)


def reset_task_app() -> None:
    """Forget the installed application, so a process can install another."""
    _installed.reset()


def task_app() -> procrastinate.App:
    """The installed procrastinate application."""
    return _installed.read()


def durable_task_queue() -> str:
    """The queue durable tool jobs are deferred onto and consumed from."""
    return _installed.durable_queue()


def worker_queues() -> tuple[str, ...]:
    """Every queue a worker of this runtime consumes."""
    return (
        CHAT_TURN_QUEUE,
        DEFAULT_QUEUE,
        MAINTENANCE_QUEUE,
        durable_task_queue(),
    )


__all__ = [
    "TaskAppNotInstalledError",
    "durable_task_queue",
    "install_task_app",
    "reset_task_app",
    "task_app",
    "worker_queues",
]
