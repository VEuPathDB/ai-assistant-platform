---
type: Backlog
title: Two memory field descriptions teach one host's science to every model
description: MemoryEntryDraft describes its name and tags fields with a P. falciparum example and an organism tag, and those strings are the tool schema a host's agent reads. They are the only biology in the repository's source.
tags: [assistant-core, memory, prompts, generality]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Read `packages/assistant-core/src/assistant_core/memory/schemas.py` and traced
where `MemoryEntryDraft` is used outside this repository.

# What I got

`memory/schemas.py:32-60` defines `MemoryEntryDraft`, whose field descriptions
read, at line 37:

```
'Short, recall-friendly title (e.g. "P. falciparum kinome size").'
```

and at line 59:

```
"Optional retrieval tags (organism, technique, dataset). "
```

No module in `packages/assistant-core/src` builds a `MemoryEntryDraft`; the one
consumer is a host's agent state
(`pathfinder: apps/api/src/pathfinder/ai/graph/state.py` line 9), so the model
is what reads these descriptions.

# Why that is wrong

A second organisation's agent is told to title its memories after a malaria
parasite's kinome and to tag them by organism. Those are instructions to a
model, not documentation for a developer: the model follows them, so the
organisation's stored memories are named and tagged in a vocabulary from a
domain it does not work in, and its retrieval quality degrades because the tags
it was coached to write do not describe its data. The runtime already has the
right pattern one package over: `render_scratchpad` takes its three coaching
strings from the host
(`packages/assistant-core/src/assistant_core/scratchpad/rendering.py`, and the
decision at `docs/knowledge/decisions/the-scratchpad-is-the-runtimes-and-the-coaching-is-the-hosts.md`).

# Why it happens

The two `Field(description=...)` strings on `MemoryEntryDraft` in
`memory/schemas.py` are model-facing coaching written for one deployment.

# Fix

Rewrite both descriptions in the runtime's own vocabulary, with no example from
any domain: a short recall-friendly title, and optional retrieval tags. Where a
deployment wants its own examples, they belong in the description of the host's
own memory tool, beside the scratchpad guidance the host already writes. Rides
the next `assistant-core` release. When PathFinder takes that tag it puts its
own examples on its `remember` tool at
`pathfinder: apps/api/src/pathfinder/ai/tools/standalone/memory_tools.py`, so
its agents keep the coaching they have today.

# What you would get

Every deployment's agent reads a memory schema in its own vocabulary, and the
repository's source names no organism.
