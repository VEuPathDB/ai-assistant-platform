---
type: Decision
title: The compactor agent is supplied by the host
description: compact_scratchpad owns the gate, the input rendering, the budget trim, the cost and the write-back. The agent that rewrites the notes arrives as a factory the gate calls, so no model id and no product vocabulary lives in the runtime and a host builds an agent only when a compaction runs.
tags: [assistant-core, scratchpad, compaction, seams]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

`assistant_core.scratchpad.compactor.compact_scratchpad` takes
`agent: Callable[[], Agent[CompactorDeps, CompactionResult]]` and calls it once,
after both ceilings are read and only when one is passed. The runtime owns
everything around the run: the gate that counts only the unpinned notes, the
markdown the agent reads, the trim that holds the replacement set under the
token ceiling, the cost from `cost_for_run`, and the transaction that replaces
the notes and logs the run.

`CompactorDeps` and `CompactionResult` are the contract the agent satisfies:
one rendered input string in, at most twenty replacement notes out.

The gate reads `compactable_count` and `compactable_tokens`, never the whole
totals. Compaction cannot touch a pinned note, so a gate that counted pinned
notes would fire on every turn of a scratchpad it cannot shrink. Both ceilings
are arguments with the runtime's own values as defaults.

The gate runs on every turn and a compaction runs rarely, so the factory keeps
the cost of building an agent, resolving a model entry and closing over
instructions on the compaction and not on the turn.

A failed model run reaches the caller. The runtime does not decide that a
turn survives a failed compaction; the node that calls this decides, and the
one it came from already does.

# What was rejected

**A model id argument.** The runtime would then build the agent, and with it
the instructions. Those instructions are where a product tells the compactor
what a redundant note looks like in its own domain, so the whole agent is the
host's and the model id rides inside it.

**A default agent built from a hard-coded model.** A default model in a
library is a bill a host did not agree to, and a version the host cannot move.

**The built agent as an eager argument.** The caller would then build one
before the gate could say there is nothing to compact, which moves the work of
one compaction onto every turn. A factory keeps the type exact and the host in
charge of the model.

**Swallowing the failure here.** The application wrapped the run in a catch
that returned `None`, and its caller wrapped the call in a second one. Two
guards over one call hide which of them fired. The runtime raises and the
caller decides.

# Anchor

`packages/assistant-core/tests/integration/scratchpad/test_compactor.py`: a
scratchpad under both ceilings is left alone and never builds an agent, a run
builds exactly one, a scratchpad of pinned notes
never triggers a run, a run over the count ceiling replaces the unpinned notes
and records the model that did it, a run over the token ceiling and a run over
both name their reason, the replacement set is trimmed oldest first, and the
run is logged with the sizes it started and ended at.
