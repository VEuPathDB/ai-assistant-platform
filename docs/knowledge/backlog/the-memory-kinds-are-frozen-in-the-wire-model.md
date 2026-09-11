---
type: Backlog
title: One host's memory kinds are frozen in the runtime's wire model
description: MemoryKind is a closed Literal of five VEuPathDB-shaped names while the store, the retriever and the tombstone index all take a kind as a plain string. A second consumer's own kind stores and retrieves but fails validation on every wire payload.
tags: [assistant-core, memory, generality]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Read `packages/assistant-core/src/assistant_core/memory/schemas.py`,
`memory/store.py`, `memory/retrieval.py` and `memory/tombstones.py`, and
compared the type of `kind` in each.

# What I got

`memory/schemas.py:14`:

```
MemoryKind = Literal["gene_set", "strategy", "preference", "knowledge", "case"]
```

and `schemas.py:22`, `MemoryValue.kind: MemoryKind`. Every other reader takes a
string: `memory/store.py:23` `kind: str` on `memory_namespace`, and the same at
`store.py:66,89,99,108,124`; `memory/retrieval.py:76`
`kinds: Sequence[str]`; `memory/tombstones.py:51` keys on
`(value.kind, compute_content_hash(value.content))` with no narrowing. Two of
the five names, `gene_set` and `strategy`, are one host's science.

# Why that is wrong

A second organisation that wants a memory kind of its own, say `dataset`, can
write it through the store and retrieve it, because those take a string, but
every payload that crosses the wire is a `MemoryValue` and fails validation on
`kind`. So the kind is unreachable from the assistant's tools and from the
memories route, and the organisation either forks the runtime or takes a
release of it to add one word. The same closed set reaches its users' browsers:
the generated client type is derived from this literal
(`pathfinder: packages/shared-ts/src/types.ts` line 272).

# Why it happens

`MemoryKind` in `memory/schemas.py` is a closed `Literal` of one deployment's
kinds, and `MemoryValue.kind` is the only place in the memory package that
narrows.

# Fix

Type `MemoryValue.kind` and `MemoryEntryDraft` as `str` with a non-empty
constraint, matching the store, the retriever and the tombstone index, and
delete `MemoryKind`. The set a deployment publishes becomes the host's: it
already names its own kinds at
`pathfinder: apps/api/src/pathfinder/transport/http/routers/memories.py` line
24. Rides the next `assistant-core` release. When PathFinder takes that tag it
declares its own five-name `Literal` in `pathfinder` and points the three
importing modules at it (`transport/http/routers/memories.py`,
`ai/tools/standalone/memory_tools.py`, `ai/lead/lead_tools.py`), then runs
`yarn generate:types`, because the generated TypeScript union becomes a string
unless the host narrows it in its own schema.

# What you would get

A second consumer adds a memory kind by naming it in its own host code, with no
release of the runtime, and its memories cross the wire like any other.
