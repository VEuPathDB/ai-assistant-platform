---
type: Decision
title: The checkpoint allowlist binds at construction, so every decode enforces it
description: build_checkpoint_serde passes the union of declared types to the JsonPlusSerializer constructor instead of with_msgpack_allowlist, which returns the receiver unchanged while the serializer already allows every module. Setting LANGGRAPH_STRICT_MSGPACK and waiting for LangGraph to flip its default were both rejected.
tags: [assistant-core, checkpointer, langgraph, serde]
generated: { by: claude-code/opus-5, at: 2026-08-24T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`assistant_core/conversation/serde.py::build_checkpoint_serde` constructs
`JsonPlusSerializer(allowed_msgpack_modules=checkpoint_types(assistant_types))`.
The allowlist is now the argument the serializer is built with, so the
serializer the checkpointer runs with decodes the declared types and refuses
the rest.

The previous form, `JsonPlusSerializer().with_msgpack_allowlist(types)`, could
not enforce anything. A default `JsonPlusSerializer()` sets its allowlist to
`True`, meaning "allow every module and warn", and `with_msgpack_allowlist`
returns the receiver unchanged when the receiver already allows everything
(`jsonplus.py:71-75` and `jsonplus.py:93-95` in the installed LangGraph). Every
allowlist the assistants declared was discarded at that call, so `TextUIPart`
warned on decode while sitting in `CORE_CHECKPOINT_TYPES`, and the allowlist
was enforced only by suites that built a second, strict serializer of their own.

# What was rejected

**Set `LANGGRAPH_STRICT_MSGPACK=true`.** It flips the default for every
`JsonPlusSerializer` in the process, including the ones LangGraph builds for
itself, and it makes the guarantee a deployment setting that a missing
environment variable silently removes. It also hands allowlist construction to
LangGraph, which derives it from the compiled graph's schemas rather than from
what an `AssistantSpec` declares.

**Wait for LangGraph to make unregistered types an error.** That is the state
the allowlist exists to survive. Waiting means the guarantee holds in the tests
and nowhere else, and the day it starts holding in production is a version bump
nobody chose.

# The consequence, stated

A type that reaches a checkpoint and is on no spec is now returned as its raw
payload with a logged refusal, rather than rebuilt with a warning. A value
under a declared field re-validates through the model that declares it, so an
omission costs a log line and not a wrong value. The union applies to every
installed assistant (`AssistantRegistry.checkpoint_types`), so a type is added
where it is declared, never to silence a warning.

# Anchor

`assistant_core/conversation/serde.py`, pinned by
`packages/assistant-core/tests/unit/conversation/test_checkpoint_serde.py` (a
declared type decodes with no serde event; an undeclared one does not survive)
and by
`pathfinder: apps/api/src/pathfinder/tests/integration/ai/test_state_read_allowlist.py`,
which reads a finished thread through `graph.aget_state` and asserts LangGraph
reports nothing.
