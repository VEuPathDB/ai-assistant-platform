---
type: Backlog
title: Three lead and sub-agent kinds are core protocol vocabulary with no runtime emitter
description: data-lead-usage, data-sub-agent-call and data-sub-agent-step are registered by the runtime and specified in PROTOCOL.md section 5.2, but nothing inside the runtime calls their emitters. They describe one host's agent topology.
tags: [assistant-core, protocol, chunks, generality]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Read the data-part table in
`packages/assistant-core/src/assistant_core/PROTOCOL.md`, the registrations in
`conversation/stream_parts/core_parts.py`, and grepped
`packages/assistant-core/src` for callers of the three emitter functions.

# What I got

`PROTOCOL.md:183-185`:

```
| `data-lead-usage` | Usage of the lead agent alone, with the fill of its context window. Reconciles on its `id`. |
| `data-sub-agent-call` | One sub-agent dispatch, with the fill of its context window. Reconciles on its `id`. |
| `data-sub-agent-step` | One event inside a sub-agent's run. |
```

They are registered at `conversation/stream_parts/core_parts.py:33,37,38`. The
emitters are `lead_usage_event` at `graph/stream_events.py:168`,
`sub_agent_call_event` at `:269` and `sub_agent_step_event` at `:294`, and
`grep -rn 'lead_usage_event\|sub_agent_call_event\|sub_agent_step_event'
packages/assistant-core/src` returns exactly those three definition lines and
nothing else. The stock graph the runtime ships says so itself
(`graph/single_agent.py:1-8`): "The graph names no phase, no role and no other
agent." The client reads them with a hard-coded group key,
`packages/assistant-client-ts/src/core/trace.ts:63`, `const LEAD = "lead"`.

# Why that is wrong

Section 5.2 opens with "The runtime defines these. An assistant MAY register
more", so a second organisation reading the core table takes the three kinds as
part of the contract it must implement, then finds the runtime emits none of
them and that they only make sense for a deployment with one lead agent
dispatching named sub-agents. An organisation with a flat agent, or a
peer-to-peer topology, has to decide whether to fake a lead or leave a
documented core kind unimplemented. The protocol is what a non-JavaScript
consumer implements from, so vocabulary in it that belongs to one host's shape
is work that consumer cannot skip with confidence.

# Why it happens

`register_core_stream_parts` in `conversation/stream_parts/core_parts.py`
registers three kinds whose payloads describe a lead-and-sub-agent topology,
and the document's table is generated from that registry.

# Fix

Move the three registrations and their payload models out of the core registry
and into the host that has the topology, leaving the emitter helpers where a
host can call them or moving them with the registrations. The document's table
is generated from the registry, so it loses the three rows in the same change.
This is a removal from the core vocabulary, which section 10 makes a major
version: `PROTOCOL.md` goes to 2.0.0 and the changelog states the three kinds
are now an assistant's own. Rides the next `assistant-core` release. When
PathFinder takes that tag it registers the three kinds on `STREAM_PARTS` from
its own composition root and regenerates its types with
`yarn generate:types`; the wire is unchanged, so no stored chunk and no client
reader moves, and the client keeps its readers under the decision at
`docs/knowledge/decisions/the-part-readers-belong-to-the-client.md`.

# What you would get

The core table names only kinds the runtime itself emits, and an organisation
with a different agent topology implements the protocol without deciding what
to do about another product's lead.
