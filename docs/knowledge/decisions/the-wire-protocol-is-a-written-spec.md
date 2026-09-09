---
type: Decision
title: The wire protocol is a written spec, verified against captured frames
description: PROTOCOL.md is prose a non-JS consumer can implement from, and a package test captures every example from a real synthetic turn and fails when the document and the runtime disagree. Generating the document from the code was rejected, because a generated page states what the types are and not what a client must do; leaving it hand-written was rejected because it drifts silently.
tags: [assistant-core, ws-v, protocol, sse, documentation]
generated: { by: claude-code/opus-5, at: 2026-08-22T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`packages/assistant-core/src/assistant_core/PROTOCOL.md` is a specification
in prose, versioned `1.0.0` under the runtime package's additive-only rule. It states the frame
grammar, cursor semantics, the turn's shape, the chunk vocabulary, the
reduction rules and the versioning contract in MUST/SHOULD language, so a
consumer in any language can implement a client from that page alone.

Four gates in
`packages/assistant-core/tests/integration/conversation/test_protocol_document.py`
keep it true:

- Every example in the document is captured from a real turn of the synthetic
  assistant, read back through the SSE reader, and compared byte for byte.
- The example set must equal the set of chunk kinds that run produced, so a
  new kind cannot appear on the wire without appearing on the page.
- The document's data-part table must equal `register_core_stream_parts`.
- The document's chunk table must equal the chunk kinds pydantic-ai's
  `vercel_ai.response_types` defines, so a library upgrade that adds a kind
  fails here.

Only two values are edited in a captured example: a generated identifier reads
as the zero UUID and a generated instant as a fixed instant. Token counts,
payload keys and error text are the run's own, so a change in any of them
fails the comparison and the page is updated with the change that caused it.

# What was rejected

**Generating the page from the models.** A page rendered from
`response_types` and the stream-part registry is true by construction, and it
answers none of the questions a client author has: when to advance a cursor,
which frame shapes exist, what terminates a turn, whether an `error` chunk
ends one, what a reducer does with a chunk addressed to a part it does not
hold. Those are rules, not types, and a generator has nowhere to put them.

**Leaving it hand-written.** The failure mode is silent and expensive: the
page keeps describing last quarter's wire, a consumer implements from it, and
the mismatch surfaces as a parse error in someone else's codebase.

The chosen shape splits the difference the way the OpenAPI spec already does
in this repository: humans write the meaning, a gate owns the facts.

# Consequences

- A protocol change is not done until the page changes with it. The failing
  test names the kind that drifted.
- The synthetic assistant is the reference implementation of the producer
  side. A chunk kind no simple assistant can produce is documented but has no
  captured example, and the page says which those are and why.
- V5's `packages/assistant-client-ts` has a written contract to implement
  against rather than a codebase to read, and its tests become the consumer
  side of the same conformance question.
