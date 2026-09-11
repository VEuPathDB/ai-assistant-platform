---
type: Backlog
title: Memory retrieval branches on site_id, which the decision says it never does
description: retrieve_relevant_memories drops a candidate whose site_id differs from the turn's, and the decision that keeps site_id on the generic turn state rests on the runtime reading none of the three fields. The code and the decision disagree.
tags: [assistant-core, memory, turns, generality]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Read `docs/knowledge/decisions/site-id-is-a-core-request-field.md` and then
every use of `site_id` in
`packages/assistant-core/src/assistant_core/memory/retrieval.py`.

# What I got

The decision states: "All three are core request fields in `PROTOCOL.md`
section 12.2, which states what the runtime does with them: it carries them to
the assistant and reads none of them. A value the runtime never branches on is
not a concept the runtime holds." Its Anchor states: "Done if the runtime ever
branches on one of the three."

`memory/retrieval.py:99-104`:

```
            if (
                site_id is not None
                and stored.value.site_id is not None
                and stored.value.site_id != site_id
            ):
                continue
```

That is a branch on the value, inside the runtime, dropping a candidate before
it is scored. The parameter is `site_id: str | None` at `retrieval.py:75`.

# Why that is wrong

Two pages of this bundle now say opposite things about the same field, and the
one a reader trusts is the one they read first. The behaviour is a policy as
well: the runtime silently decides that a memory written on one data host is
irrelevant on another. A second organisation whose deployment serves several
data hosts and whose users expect their memories everywhere cannot turn the
filter off, because it is not a seam, and it gets no signal that its memories
were dropped. The decision's own test for its own soundness has been tripped,
so either the filter or the decision is now wrong, and nothing in the
repository says which.

# Why it happens

`retrieve_relevant_memories` in `memory/retrieval.py` filters candidates on
`MemoryValue.site_id`, a field the decision classes as carried and unread.

# Fix

Take the filter out of the runtime and let the caller state it: give
`retrieve_relevant_memories` a `keep: Callable[[MemoryValue], bool] | None`
argument in place of `site_id`, and drop the branch. The runtime then scores
and ranks, which is what it owns, and the host decides which memories are in
scope, the same split as the scratchpad coaching and the compactor agent.
Amend `docs/knowledge/decisions/site-id-is-a-core-request-field.md` to say the
runtime reads none of the three again, which is true once the branch is gone.
Rides the next `assistant-core` release. When PathFinder takes that tag it
passes the site predicate at its one call site,
`pathfinder: apps/api/src/pathfinder/ai/graph/_lead_turn.py` line 81, keeping
today's behaviour.

# What you would get

Retrieval ranks every candidate the host allows, the scope rule lives with the
host that has a scope, and the decision page is true of the code again.
