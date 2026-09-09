---
type: Decision
title: The runtime ships its own migration chain, and its baseline never runs twice
description: assistant-core carries an alembic history under src/assistant_core/alembic with the version table alembic_version_assistant_core, exposes assistant_core.migrate.upgrade_head(connection) and the OWNED_TABLES list every other reader of the four names reads, and its baseline no-ops only when all four tables exist, refuses a partial set and refuses to downgrade, so no deployment has to be stamped by hand and none is half-built in silence.
tags: [assistant-core, persistence, migrations, packaging]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

The runtime owns four tables: `conversations`, `messages`,
`conversation_events` and `memory_tombstones`. It now ships the history that
creates them, instead of leaving every host to hand-write it.

The shape is the one `veupathdb-mcp` already uses, copied on purpose so the two
chains read alike:

| part | where |
| --- | --- |
| the history | `src/assistant_core/alembic/`, packed into the wheel |
| the version table | `alembic_version_assistant_core` |
| the entry point a host calls | `assistant_core.migrate.upgrade_head(connection)` |
| the standalone command | `python -m assistant_core.migrate` |
| the four table names | `assistant_core.migrate.OWNED_TABLES` |
| the autogenerate filter | `assistant_core.migrate.include_object` |

A host runs its own chain and this one on a single connection, in that order,
because the runtime's tables name host tables in foreign keys. The two chains
never read each other's version table, so they share a database without
touching each other.

**The baseline is idempotent, and only for the whole set.** `2026_09_09_0001`
asks the inspector for all four tables. It returns without doing anything when
all four are there, builds them when none are, and raises naming the ones
present and the ones missing when the set is partial. `conversations` and
`messages` are names a second host may already use for tables of its own, so a
partial match is a collision, not a database this chain built.

**The baseline refuses to downgrade.** A database stamped at it may hold four
tables a host chain created, and dropping them would take a host's data with
them.

The host keeps its historical revisions for those four tables: they are that
database's history. It writes no further revision for them.

**Autogenerate is scoped to the four.** The chain's `env.py` passes
`include_object`, which keeps a table only when `OWNED_TABLES` names it. Without
it, `alembic revision --autogenerate` run against a host's development database
writes an `op.drop_table` for every host table, because the declarative base the
runtime exports is the base a host maps its own tables on. `OWNED_TABLES` is the
one list: the baseline, the filter, the host-contract test and a host's own
filter all read it.

# What was rejected

**A stamp step in the runbook.** `veupathdb-mcp` states that rule for its own
two tables, and it works, but it is a one-shot manual action on every database
that already exists: development, a researcher's, every deployment. A missed
stamp makes the baseline try to create four tables that are already there and
the process refuses to start. Guarding the baseline costs a dozen lines once
and removes the action from every runbook.

**Leaving the four tables in the host's chain.** It is where they are today, and
it means a second host of the runtime hand-writes four `create_table` calls,
two check constraints, five indexes and a cycle-closing foreign key from
reading the models. The wire contract the runtime publishes would then rest on
schema only one host has.

**A shared `env.py`.** The runtime's, the MCP server's and the host's are three
near-identical files of about seventy lines. They stay three files, for the
reason already recorded for the settings-source scaffold and the logging setup:
the distributions share no dependency edge, and a micro-distribution for
seventy lines of alembic boilerplate buys less than it costs.

# Anchor

`packages/assistant-core/tests/integration/persistence/test_migration_chain.py`:
a database carrying only the host contract, migrated by this chain, shows no
difference against `Base.metadata`; the cycle-closing foreign key a metadata
diff cannot see is read from the built schema; a database built from the models
is stamped at the baseline with its rows intact; a database holding one of the
four is refused by name; and a database holding a table the chain does not own
draws an operation without the filter and none with it.

`packages/assistant-core/tests/unit/persistence/test_migration_baseline.py`: the
baseline's `downgrade` raises, and the filter keeps the four names and drops
every other.

`packages/assistant-core/tests/packaging/test_wheel_carries_the_migration_chain.py`:
the wheel carries `env.py`, the template and every revision, so an installed
distribution can run the chain.
