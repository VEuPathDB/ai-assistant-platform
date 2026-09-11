---
type: Decision
title: A set only a host can enumerate is a validated string, not a Literal
description: MemoryValue.kind and AdmissionRecord.credential_mode are non-empty snake_case strings the runtime validates for shape and never for membership. Keeping the closed Literal, and validating a value against the assistant's declared set, were both rejected.
tags: [assistant-core, memory, mcp, admission, generality]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: stable
---

# What was decided

`assistant_core/memory/schemas.py::MemoryValue.kind` and
`assistant_core/mcp/admission.py::AdmissionRecord.credential_mode` are `str`
fields with one rule each: a non-empty snake_case name, enforced by a
`field_validator` that names the shape in its refusal. The runtime states the
shape because the value is a namespace segment and an operator-facing word;
which names exist is the deployment's.

A host publishes its memory kinds on `AssistantSpec.memory_kinds` and serves
them on its own route. The credential vocabulary is the deployment's too: the
runtime interprets `NO_CREDENTIAL`, the one mode under which a source is never
asked for a credential, and hands every other mode to the host's credential
callback with the whole record.

The same split applies to what a model reads. `MemoryEntryDraft`'s field
descriptions are the tool schema an agent sees, so they name a short title and
optional tags and no example from any domain. A host that wants to coach its
model with examples writes them on its own memory tool, beside the scratchpad
guidance it already supplies
([the scratchpad decision](the-scratchpad-is-the-runtimes-and-the-coaching-is-the-hosts.md)).

# What was rejected

**Keeping the closed `Literal`s.** Five memory kinds and three credential modes
were one deployment's vocabulary in a package that serves any. A second
organisation could store and retrieve a kind of its own, because the store, the
retriever and the tombstone index all take a string, but every wire payload
failed validation on it; an unlisted credential mode was refused at
construction by `extra="forbid"`. Either cost a release of this repository to
add one word the runtime then ignored.

**Validating a kind against the assistant's declared set.** The runtime holds
`AssistantSpec.memory_kinds`, so a model could refuse a kind no assistant
declared. It was rejected because a `MemoryValue` is validated where no turn
and no spec are in scope, such as a row read back from the store or a payload
crossing the wire, and a rule that holds in one of those places and not the
others is worse than no rule.

**A free string with no shape.** The kind is a namespace segment and the mode
is a word an operator reads in configuration. A value with a space or a slash
in it would be accepted here and refused, or silently reshaped, somewhere else.

# Anchor

`packages/assistant-core/tests/unit/memory/test_schemas.py`: a kind the runtime
never named validates, a kind that is not a snake_case name is refused, and the
draft's descriptions name no domain.
`packages/assistant-core/tests/unit/mcp/test_admission.py` and
`tests/unit/mcp/test_resolution.py`: a deployment's own credential mode is
admitted, a mode that is not a name is refused, and every mode but
`NO_CREDENTIAL` reaches the host's callback.
