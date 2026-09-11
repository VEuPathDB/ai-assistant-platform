---
type: Backlog
title: A kind the runtime emits is absent from the data-part table
description: The runtime writes data-scratchpad-updated from four call sites in its own scratchpad tools, but the kind is unregistered and so missing from PROTOCOL.md section 5.2. The table is checked against the registry, not against what the runtime emits.
tags: [assistant-core, protocol, chunks, scratchpad]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Grepped `packages/assistant-core/src` for `data-memory-retrieved` and
`data-scratchpad-updated`, read the registrations in
`conversation/stream_parts/core_parts.py`, the table in `PROTOCOL.md` section
5.2, and the assertion in
`tests/integration/conversation/test_protocol_document.py`.

# What I got

`graph/stream_events.py:134-140` defines `scratchpad_updated_event`, which
returns a `DataChunk` of type `data-scratchpad-updated`, and the runtime's own
scratchpad tools call it four times:
`scratchpad/tools.py:126,161,179,201`, each as `extra=[scratchpad_updated_event()]`.
`graph/stream_events.py:109-127` defines `memory_retrieved_event`, type
`data-memory-retrieved`, and `grep -rn 'memory_retrieved_event'
packages/assistant-core/src` returns only that definition.

Neither kind is in `register_core_stream_parts`
(`conversation/stream_parts/core_parts.py:28-43`), so neither appears in the
twelve rows of the generated table at `PROTOCOL.md:177-190`. The assertion that
keeps the table honest is
`tests/integration/conversation/test_protocol_document.py:149`:

```
    assert set(_TABLE_KIND.findall(_section("data_parts"))) == registry.kinds()
```

which compares the table to the registry and never to the emitters.

# Why that is wrong

`docs/knowledge/decisions/a-registered-data-kind-is-not-a-protocol-kind.md`
rejected adding these kinds on the ground that "the runtime registers none of
them", and closes with the rule "A kind belongs in the table when the runtime
emits it". The runtime does emit `data-scratchpad-updated`, from four call
sites in a subsystem the runtime owns, so that rule is met and the page's
premise is out of date. A second consumer writing a client from `PROTOCOL.md`
alone therefore receives a chunk the document does not name, whose meaning is
that the reader must invalidate its scratchpad view: it either drops the chunk
and shows stale notes after every scratchpad write, or reverse-engineers the
kind from another organisation's client.

# Why it happens

The table is generated from `StreamPartRegistry`, and
`register_core_stream_parts` does not register the kind that
`assistant_core.scratchpad.tools` emits.

# Fix

Register `data-scratchpad-updated` with its `ScratchpadUpdatedPayload` in
`register_core_stream_parts`, which adds its row to the table and to the
schema index. Adding a data part is additive, so `PROTOCOL.md` goes to 1.8.0
with a changelog line. Leave `data-memory-retrieved` unregistered while no
runtime module calls its emitter, and say so in the decision page when it is
amended, so the two are distinguished by the rule rather than by accident.
Rides the next `assistant-core` release. When PathFinder takes that tag it
regenerates with `yarn generate:types`; the kind reaches its client today
through `isKnownChunkKind`, so no renderer changes.

# What you would get

A client written from the document alone knows to invalidate its scratchpad,
and the table names every kind the runtime emits.
