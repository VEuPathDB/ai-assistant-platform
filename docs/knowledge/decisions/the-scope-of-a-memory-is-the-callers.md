---
type: Decision
title: Retrieval ranks, and the caller says which memories are in scope
description: retrieve_relevant_memories takes a keep predicate in place of site_id, so the runtime scores and ranks and the host states the scope rule. A hook on the AssistantSpec, and keeping the site filter behind a flag, were both rejected.
tags: [assistant-core, memory, turns, seams]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: stable
---

# What was decided

`assistant_core/memory/retrieval.py::retrieve_relevant_memories` takes
`keep: Callable[[MemoryValue], bool] | None` and no `site_id`. It searches each
declared kind, drops what the writer marked `auto_retrieve=False`, drops what
`keep` refuses, scores the rest and returns the global top hits. A caller that
supplies no predicate ranks every candidate.

`auto_retrieve` stays a runtime rule: it is a field of the runtime's own model,
written by whoever wrote the memory, and it says the memory is not for
graph-time recall at all.

Scope is not that. A deployment that serves several data hosts decides whether
a memory written against one is relevant against another, and a deployment that
serves one has no such rule. The host owns it and passes it at the call site,
which keeps
[siteId, mode and phase are core request fields](site-id-is-a-core-request-field.md)
true of the code: the runtime carries the three and branches on none.

# What was rejected

**Keeping the site filter in the runtime.** It reads a field the runtime is not
supposed to interpret, it silently drops candidates a deployment may want, and
it is not a seam: an organisation whose users expect their memories on every
data host could not turn it off.

**A retrieval hook on the `AssistantSpec`.** The spec already carries
`memory_kinds`, so a `memory_filter` beside it looks natural. It was rejected
because retrieval is called with a store, a user and a query and no spec in
hand, so the hook would have to be resolved from the registry at the point of
use; the predicate is an argument the caller already has.

**A boolean argument that turns the filter on.** It keeps the policy in the
runtime and adds a flag, so the runtime still decides what "the same scope"
means and a host with any other rule is no better off.

# Anchor

`packages/assistant-core/tests/unit/memory/test_retrieval.py`: a predicate
keeps the candidates it allows, a call with no predicate ranks them all, and a
memory marked not auto-retrieve is withheld either way.
`packages/assistant-core/tests/integration/memory/test_retrieval_filtering.py`
drives the same three over the real store.
