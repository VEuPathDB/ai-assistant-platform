---
type: Backlog
title: The typed-part contract is keyed on one organisation's reverse-DNS name
description: A tool server must emit org.veupathdb.assistant/streamPart and org.veupathdb.assistant/maxCallSeconds to get a typed part or a call budget, the key is a literal in two distributions, and no decision covers it.
tags: [assistant-core, mcp-conformance, mcp, naming]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Read `packages/assistant-core/src/assistant_core/mcp/untrusted.py` and
`packages/mcp-conformance/src/mcp_conformance/_evidence.py`, and searched
`docs/knowledge/decisions/` for a page about the key.

# What I got

`mcp/untrusted.py:19`:

```
STREAM_PART_META_KEY = "org.veupathdb.assistant/streamPart"
```

`_evidence.py:12` carries the same literal, and `_evidence.py:16` adds
`MAX_CALL_SECONDS_META_KEY = "org.veupathdb.assistant/maxCallSeconds"`. Both are
module constants with no setting and no argument behind them. The nearest
decision, `docs/knowledge/decisions/the-client-scope-names-the-organisation.md`,
settles the npm scope of the client package and says nothing about a `_meta`
key.

# Why that is wrong

Reverse-DNS `_meta` namespacing is ordinary MCP practice, so the shape is
right and the owner is wrong: a third-party tool server that wants its
structured payload rendered as a typed part, or one call held to a longer
budget, must annotate its tools with a key naming an organisation it has no
relationship with. A server that serves two deployments then carries one
deployment's vendor key in its public tool definitions, and a second
organisation standing up its own runtime either adopts the same foreign key or
patches two distributions. The conformance suite reads the same literal, so the
key is also what a server is tested against.

# Why it happens

`STREAM_PART_META_KEY` and `MAX_CALL_SECONDS_META_KEY` are hard-coded literals
in `mcp/untrusted.py` and `mcp_conformance/_evidence.py`.

# Fix

Make the namespace a value rather than a literal: one constant holding the
default `org.veupathdb.assistant`, read by both distributions, with the runtime
taking an override from its settings and the conformance suite taking
`--mcp-meta-namespace`, and a deployment that sets one accepting a server's
own key. Record the default and the override in a decision page, so the key
name stops being an accident of the first host. Rides the next
`assistant-core` and `veupathdb-mcp-conformance` releases together, because the
two constants must agree. When PathFinder takes those tags it sets no override
and its tool server keeps emitting today's keys.

# What you would get

A third-party tool server declares a typed part under a key its own deployment
chose, and the default keeps every server that works today working.
