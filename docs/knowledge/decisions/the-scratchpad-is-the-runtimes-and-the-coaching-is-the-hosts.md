---
type: Decision
title: The scratchpad is the runtime's and the coaching is the host's
description: The runtime owns the notes, the nine tools, the toolset filter and the rendered index. What the model is told to write down and what is worth promoting arrive as a guidance argument, and a host attaches the toolset to whichever agents it wants.
tags: [assistant-core, scratchpad, seams, tools]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

`assistant_core.scratchpad` owns a thread's working notes: the models, the two
tables, the repository, the notebook that opens a session per call, the nine
tools, the toolset that filters them, and the index the agent reads.

`build_scratchpad_toolset(promoted_kind=..., guidance=...)` returns an
`AbstractToolset[AssistantDeps]`. A host passes it in the `toolsets` list of
any agent it wants to take notes; there is no registration step and the runtime
names no agent. The deps type is contravariant in pydantic-ai, so an agent
whose deps subclass `AssistantDeps` accepts the toolset unchanged.
`promoted_kind` is the memory kind a promoted note is written under, and it is
required, because the kinds are the host's
([a set only a host can enumerate is a validated string](a-closed-set-the-host-owns-is-a-validated-string.md)).

`render_scratchpad(notes, total_count=..., guidance=...)` renders the header,
the pinned section and the recent section, and appends the host's text.
`ScratchpadGuidance` carries three strings. `empty` and `populated` reach the
index, because a host coaches differently in the two states. `promote` reaches
the description of `promote_to_memory`: `build_scratchpad_toolset` appends it
to that tool's docstring when the toolset is built, and an empty string appends
nothing. The runtime supplies none of the three: what is worth writing down and
what is worth keeping name the work the agent does, and that is the product's.

The tools' own docstrings say what a tool does and never what a product's notes
look like. A docstring that told the model to note "searches and their
parameters" would carry one product's vocabulary into every deployment, so the
one tool whose choice needs an example takes that example through the seam.

A turn that carries no thread is a permanent condition, not a retry: the tools
return `ScratchpadUnavailable`, a typed refusal with `ok: false` and code
`NOT_FOUND`, and the call is summarized with status `warn`. Every other
failure the model can fix, such as an id that is not there or a field over its
limit, raises `ModelRetry`.

# What was rejected

**A registration call that names the agents.** The application it came from
imported the builder into each agent module. That is the same thing an
argument does, with a list the runtime would have to hold. The toolset is a
value; the host places it.

**A single guidance string.** One string cannot say "here is what to start
writing", "here is what to do before you finish" and "here is what is worth
keeping" at once. The three land in different places, so the seam carries three.

**Leaving `promote_to_memory` with no way back to a concrete example.** A tool
docstring is the tool description the model reads, and it is the only
instruction the model has for deciding what to promote. A generic sentence
promotes more notes and less relevant ones, so the host's example reaches the
description rather than only the index.

**Keeping the product's coaching in the runtime's default.** A default that
mentions searches, parameters or typed deltas is a product's vocabulary
wearing the runtime's name. The default is empty, and an index with no
guidance is a complete index.

**Reusing the tool-error payload of the MCP server distribution.** That type
lives in a distribution the runtime may not depend on. `ScratchpadUnavailable`
holds the same three fields and the same code, so what a client sees does not
change.

# Anchor

`packages/assistant-core/tests/unit/scratchpad/test_rendering.py`: an empty
scratchpad carries the host's empty guidance, a host that supplies none gets
the index alone, the header counts the notes and the pinned ones, and the
budget drops the oldest unpinned notes while a pinned note is never dropped.
`packages/assistant-core/tests/unit/scratchpad/test_toolset.py`: the host's
`promote` sentence is appended to the `promote_to_memory` description, a host
that supplies none gets the docstring alone, and the sentence reaches no other
tool.
`packages/assistant-core/tests/integration/scratchpad/test_tools_read.py`: an
empty scratchpad offers only `note`, a filled one offers all nine, and a read
tool called twice in a row disappears.
