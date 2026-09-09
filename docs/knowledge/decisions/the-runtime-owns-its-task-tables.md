---
type: Decision
title: The runtime owns its task tables, and `users` is its one host-table contract
description: background_tasks and task_progress move into assistant-core and onto its migration chain, because every column in them is a runtime concept the wire protocol already publishes; users stays the host's, and is the single table a host must supply, with one column.
tags: [assistant-core, persistence, durable-tasks, protocol]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# The question

`assistant_core/persistence/models.py` declares foreign keys into two tables it
does not define, `users` and `background_tasks`, and the suite fabricates both.
Does the host supply them, or does the runtime own them and ship migrations?

# What was decided

The two tables are different in kind, and the answer differs for each.

**`background_tasks` and `task_progress` become the runtime's**, and move onto
the chain this package ships. **`users` stays the host's**, and is the runtime's
single host-table contract: *a host supplies a `users` table with a uuid `id`.*
`background_tasks.user_id` keeps its foreign key into it.

The runtime already owns the whole feature except the storage:

- `assistant_core/graph/durable.py` declares `DurableToolSpec` and the registry.
- `assistant_core/graph/turn_state.py` declares `DurableCall`,
  `PendingDurableCall` and `DurableTaskResult`.
- `assistant_core/graph/stream_events.py` builds `background_task_started`,
  `task_progress` and `task_completed`.
- `PROTOCOL.md` section 6.1 defines a turn suspended on a durable task, and
  `assistant-client-ts/tests/conformance/durableTask.test.ts` gates the
  consumer side of it.

So the runtime publishes a wire contract for durable tasks. Leaving the storage
out means a second host re-derives the whole subsystem from the document.

The column lists settle which table is whose. `users` carries `external_id`,
`monthly_cost_limit_usd`, `eval_data_consent` and `eval_notice_seen_at`:
product columns about a person's consent, and unambiguously the host's.
`background_tasks` carries `conversation_id`, `tool_name`, `tool_call_id`,
`status`, `args`, `phase_overrides`, `result`, `error` and
`estimated_duration_seconds`. Every one is a runtime concept, and
`phase_overrides` holds the per-role model and reasoning map that `PROTOCOL.md`
already declares as core request fields.

The contract is now `users` alone, and the suite fabricates one table of one
column. `background_tasks` and `task_progress` are revision
`2026_09_09_0004`. The baseline creates `conversation_events` before that
revision exists, so the baseline leaves `conversation_events.task_id` without
its foreign key and revision `2026_09_09_0004` adds it, whichever chain
created the table it points at: the revision checks for a key on `task_id` and
writes one when there is none, on the path that creates the tables and on the
path that finds a host's.

**The baseline revision was rewritten after it shipped.** `2026_09_09_0001`
went out under `v0.3.0a1`, `a2` and `a3` creating `conversation_events` with a
key into `background_tasks`, which only worked because the host was required
to fabricate that table first. Removing that requirement is this decision, so
the shipped bytes and this decision cannot both stand: on a clean database
they raise `relation "background_tasks" does not exist` before any later
revision runs. The rewrite is safe because no database outside the test suite
has run this chain, and because a database that *had* run the shipped baseline
necessarily holds a host-supplied `background_tasks` and no `task_progress`,
which revision four names and refuses rather than stamping over.

**Taking this release needs the durable queue drained.** The durable job's
kwargs lost `veupathdb_auth_token` and gained `job_context`. The job names did
not change, so an old in-flight job reaches the new worker and fails on an
unexpected keyword argument.

# What was rejected

**Keeping both tables in the host and dropping the two foreign keys.** It leaves
`conversation_events.task_id` pointing at nothing a database can check, puts a
contract the runtime publishes behind an implementation only one host has, and
makes the second host re-derive the subsystem from prose.

**Keeping both tables in the host and keeping the foreign keys**, which is the
state this decision replaces. It is coherent, and it is right about `users`.
It is wrong about `background_tasks`: there is nothing product-shaped in that
table, and calling it a host table is what forces the re-derivation.

# The cost, stated

`procrastinate` becomes an `assistant-core` dependency, and a host that wants
the runtime without background tasks pays for it. That is accepted because the
protocol already requires the feature: a client conformance test asserts the
three chunks.

# Anchor

`packages/assistant-core/tests/unit/persistence/test_host_table_contract.py`:
the runtime's foreign keys reach `users.id` and no other host column, and the
whole suite runs against a fabrication that carries exactly that column.
`tests/integration/persistence/test_migration_chain.py` adds the key from a
task-tagged chunk to the task table on both paths, the cascade that removes a
task and its progress with its thread, and the refusal of a half-built pair.
