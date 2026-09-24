---
type: Decision
title: The runtime counts the cost and the host sets the limit
description: assistant_core.quota accumulates spend per user per application per payer and reports a period snapshot of the deployment's spend, but the budget itself arrives as an argument, because the runtime holds no user record and no product policy.
tags: [assistant-core, quota, pricing, tenancy, persistence]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-24T00:00:00Z }
status: stable
---

# What was decided

`assistant_core.quota` owns the arithmetic of a monthly USD budget:
`current_period_start` and `next_period_start` fix the UTC month,
`accumulate` upserts the `monthly_usage` row of the calling application, and
`get_current` sums every application of one user into a `QuotaStatus`. The
table is the runtime's and joins its migration chain.

`get_current` takes `limit_usd` as a keyword argument. The runtime does not
read a limit from settings, and it does not read the `users` row. Two facts
force that:

- The runtime declares exactly one host table, `users` with a uuid `id`
  (see [The runtime owns its task tables](the-runtime-owns-its-task-tables.md),
  proposed, executed in the task-table move).
  A per-user limit column would be a second column in that contract, and every
  host would have to carry it whether or not it offers per-user overrides.
- A limit is product policy. What a caller at a hundred percent is told, and
  whether a user may exceed it, is the host's decision, so the runtime reports
  the numbers and raises nothing.

Every row names who paid. `accumulate` takes `paid_by`, a
`PaidBy` (`assistant_core.platform.types`) that is `deployment` or `user`, with
no default, and the upsert keys on it, so one period of one application holds
at most one row per payer. `get_current` counts the `deployment` rows only: a
user who runs a model on their own provider key spends nothing of the budget
the deployment pays for. `get_period_totals(session, user_id, paid_by=...)`
reads one payer's spend, so a host can show the own-key figure beside the
capped one. The runtime does not decide who paid: which key a model call ran on
is the host's knowledge, and the charge carries it.

`assistant_core.pricing.lookup_per_mtok_prices(provider, model, at=...)` reads
the packaged `genai_prices` snapshot for one pair. Which pairs matter is the
host's model catalog, so the function takes the pair and holds no catalog of its
own. A snapshot price can start on a date or hold for part of a day, so the
lookup takes the instant to price at and defaults it to now.

# What was rejected

**A `RuntimeSettings` field for the default limit.** It is one line, and the
settings source already exists. It was rejected because the value is not a
property of the runtime: two assistants on one deployment can have different
budgets, and a settings field makes the limit a per-process constant that the
per-request caller cannot vary.

**Reading the override from `users`.** The column exists in the host that has
this feature today. It was rejected because it widens the one host-table
contract for a feature no other host has to offer, and because it puts a host's
column name inside the runtime.

**Raising when the budget is spent.** The runtime knows the numbers, not the
consequence. A host that returns 429, a host that warns at eighty percent and a
host that only records usage all read the same `QuotaStatus`.

**A default payer on `accumulate`.** A default of `deployment` would keep
every existing call compiling. It was rejected because a host that adds its
users' own keys and forgets one call site would then bill that user's spend to
the deployment's cap without an error. With no default, the upgrade names the
payer at every call, and the column carries no server default either.

**A separate table for spend on a user's key.** It would duplicate the upsert,
the period arithmetic and the application scoping, and a host would read two
tables to answer one question. One row per payer in the same table keeps one
write path.

**Leaving spend on a user's key unrecorded.** The key is the user's, so the
deployment owes nothing. It was rejected because the tokens are still usage:
the host shows them, and an operator reading `monthly_usage` must see every
model call that ran through the deployment.

# Anchor

`packages/assistant-core/tests/unit/quota/test_periods.py` fixes the UTC month
boundaries; `tests/unit/quota/test_pricing.py` fixes the three price fields and
the unknown pair; `tests/integration/quota/test_quota_per_application.py`
proves one row per application, one cap across them, and no row for a charge of
nothing; `tests/integration/quota/test_quota_by_payer.py` proves one row per
payer, a cap that ignores the user's own spend, the two totals read apart and
an unknown payer refused before a row; `tests/unit/quota/test_the_payer_is_required.py`
proves that mypy refuses a charge that names no payer;
`tests/integration/persistence/test_migration_chain.py` proves that revision
`2026_09_24_0005` moves every existing row to `deployment`.
