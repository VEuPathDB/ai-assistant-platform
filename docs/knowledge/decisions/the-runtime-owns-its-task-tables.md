---
type: Decision
title: The runtime owns its task tables, and `users` is its one host-table contract
description: background_tasks and task_progress move into assistant-core and onto its migration chain, because every column in them is a runtime concept the wire protocol already publishes; users stays the host's, and is the single table a host must supply, with one column.
tags: [assistant-core, persistence, durable-tasks, protocol]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: proposed
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

Until the move lands, `conversation_events.task_id` still names a host
`background_tasks`, so the contract the suite fabricates is two tables of one
column each. After it, the contract is `users` alone.

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
the runtime's foreign keys reach `users.id` and `background_tasks.id` and no
other host column, and the whole suite runs against a fabrication that carries
exactly those two columns.
