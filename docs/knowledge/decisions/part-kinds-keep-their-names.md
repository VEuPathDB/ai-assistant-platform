---
type: Decision
title: Part kinds keep their names when the taxonomy opens
description: Opening the data-part registry does not namespace the kinds, because every kind string is persisted in conversation_events and replayed to rebuild a message.
tags: [transport, sse, data-parts, ws2]
generated: { by: claude-code/opus-5, at: 2026-08-21T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was found

Seam A2 replaced the closed `data-*` union with a registry: core registers the runtime parts, each product registers its own, and the OpenAPI schema index reads the registry. The obvious companion change is to namespace the product kinds - `data-graph-snapshot` becomes `data-strategy.graph-snapshot` - so two assistants can never collide.

A kind string is not only a dispatch key. Every emitted chunk is stored verbatim in `conversation_events.chunk`, and history is rebuilt by replaying those rows: `GET /api/v1/conversations/{id}/events/snapshot` returns the stored chunks and the frontend reducer turns each one back into a message part. The renderer is found by the kind with `data-` stripped.

# The decision

Register the kinds under the names they already have. Namespacing waits until a second assistant registers parts.

Renaming today would make every stored chunk unrenderable - a saved conversation would replay as a column of "Unknown data part" toasts - and the only alternative is a migration that rewrites the chunk JSON of every row for a collision that no shipped code can produce. The registry accepts a namespaced kind already: `data-other.gene-view` registers and maps to the `otherGeneView` schema field, so nothing has to change here when the second assistant arrives.

# Anchor

`packages/assistant-core/src/assistant_core/conversation/stream_parts/registry.py` holds the kind rules; `pathfinder: packages/shared-ts/src/types.ts` holds `KnownDataPartKind`. Done if a kind is renamed without a replay path for the rows already in `conversation_events`.
