"""The job queue the host opens and the runtime defers onto.

The runtime owns no connection pool and no schema, so the host builds the
procrastinate application and installs it here once per process.
"""

from __future__ import annotations

import procrastinate


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

    def install(self, app: procrastinate.App) -> None:
        self._app = app

    def reset(self) -> None:
        self._app = None

    def read(self) -> procrastinate.App:
        if self._app is None:
            raise TaskAppNotInstalledError
        return self._app


_installed = _TaskApp()


def install_task_app(app: procrastinate.App) -> None:
    """Run this process's durable work on the host's procrastinate application."""
    _installed.install(app)


def reset_task_app() -> None:
    """Forget the installed application, so a process can install another."""
    _installed.reset()


def task_app() -> procrastinate.App:
    """The installed procrastinate application."""
    return _installed.read()


__all__ = [
    "TaskAppNotInstalledError",
    "install_task_app",
    "reset_task_app",
    "task_app",
]
