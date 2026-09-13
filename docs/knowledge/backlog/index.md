# Backlog

Everything known to be outstanding in this repository, ranked. An item is
removed when it is done, not marked done: this file and the items beside it are
exactly what remains.

## Ranked

Ordered by what stands between a second organisation and its own assistant on
this runtime: first what it cannot do without forking or a release, then what
misleads whoever implements the wire, then naming.

1. [The age timeout releases a durable job a live worker is still running](the-age-timeout-releases-a-job-a-live-worker-still-runs.md) - one number answers "is anything running this?" and "has this run too long?", so a long durable call is failed under the worker that then reports its result.
2. [A pending task row the queue holds no job for is settled by nobody](a-pending-row-the-queue-holds-no-job-for.md) - the row is committed before the defer, so a killed process strands one that the job-driven sweep cannot see.
3. [Two definitions of an active durable task](one-definition-of-an-active-task.md) - `has_active_task` reads three statuses, the repository publishes four, and a host keeps a third copy.
