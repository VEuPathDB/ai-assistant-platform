"""The queue and job names the runtime owns, and the host wires."""

# Durable tool jobs run here, so a long tool never blocks a chat turn.
DURABLE_TASK_QUEUE = "verification"
# One chat turn is one job on this queue.
CHAT_TURN_QUEUE = "chat_turn"
# Periodic housekeeping, including the stalled-job sweep.
MAINTENANCE_QUEUE = "maintenance"
DEFAULT_QUEUE = "default"

CHAT_TURN_TASK = "chat_turn:run"
RELEASE_STALLED_JOBS_TASK = "maintenance:release_stalled_jobs"

# Every queue a worker of this runtime consumes.
WORKER_QUEUES = (
    CHAT_TURN_QUEUE,
    DEFAULT_QUEUE,
    MAINTENANCE_QUEUE,
    DURABLE_TASK_QUEUE,
)

_DURABLE_JOB_PREFIX = "durable:"


def durable_job_name(tool_name: str) -> str:
    """The procrastinate job one durable tool defers and the worker consumes."""
    return f"{_DURABLE_JOB_PREFIX}{tool_name}"


__all__ = [
    "CHAT_TURN_QUEUE",
    "CHAT_TURN_TASK",
    "DEFAULT_QUEUE",
    "DURABLE_TASK_QUEUE",
    "MAINTENANCE_QUEUE",
    "RELEASE_STALLED_JOBS_TASK",
    "WORKER_QUEUES",
    "durable_job_name",
]
