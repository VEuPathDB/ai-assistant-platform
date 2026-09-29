---
type: Backlog
title: The write-through store has no host left
description: WriteThruStore keeps a per-process cache that wins over the database, which is wrong for any host whose api and worker write the same rows; its last host stopped using it, so only its own test reads it.
tags: [assistant-core, platform, persistence]
generated: { by: claude-code/opus-5, at: 2026-09-29T00:00:00Z }
status: proposed
---

# The write-through store has no host left

**What I did.** Read `assistant_core/platform/store.py::WriteThruStore` and
searched the hosts that install this runtime for a subclass.

**What I got.** The class keeps an in-memory copy of every row it saved and
answers reads from that copy before the database. The one host that extended
it ran an api process and a worker process against the same tables, so a row
the worker rewrote stayed old in the api until that process restarted, and a
later save from the api wrote the old row back. That host now reads and writes
through its repositories; no subclass of `WriteThruStore` remains anywhere but
`tests/unit/platform/test_write_thru_store.py`.

**Why that's wrong.** A runtime whose turns run in a worker cannot offer a
per-process cache as a store: two processes hold two truths. The class invites
the bug in the next host.

**Fix.** Delete `WriteThruStore`, `Identifiable` and their test in the next
release; a host that wants a cache keys it on a version column the database
owns.

**What you'd get.** One place a row lives, the database, and no runtime type
that says otherwise.
