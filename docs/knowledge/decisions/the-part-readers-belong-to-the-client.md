---
type: Decision
title: The readers over a message's parts belong to the client
description: The trace, the usage totals, one durable task's lifecycle and the running phase are folds over parts the protocol defines, so they live in the client and not in the application. Each payload is read with the types the wire states, so two readers of one chunk cannot report different numbers.
tags: [assistant-client, protocol, usage, durable-tasks]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

The core ring reads a message's parts, and a host renders what it returns:

- `buildTrace` groups a turn's calls into runs.
- `runningPhase` names the dispatch a turn still has open.
- `turnUsage` and `threadUsage` total what a turn and a thread spent.
- `taskLifecycle` and `orderedLanes` read one durable task's progress and its
  outcome off the thread, one lane at a time.
- `isToolPart`, `isDataPart` and `readSubAgentStep` are exported, so a host
  addresses a call id without re-deriving what a part is.

The `./ai-sdk` ring adds `toTraceParts`, which reads the AI SDK's own part
shapes as the shapes above: it collapses `approval-responded` onto
`input-available`, drops the kinds the protocol does not name, and folds a
summary the SDK's reducer left beside a call onto the call.

**Every payload is read with the type the wire states.** `tokens` is a number
and `costUsd` is a decimal string; a field of another type reads as nothing
spent, and a payload that is not an object is not read at all. A lead-usage
part reconciles on its id, so the last one on a turn is that turn's, never the
sum of the writes that reached it.

**The concepts a host owns are arguments.** The lane inside a task's
`toolSpecific` is named by the producer, so `taskLifecycle` takes a `laneOf`
callback and reads one sequence without it. The model string, the phase label
and every format stay in the host.

# Why

Two readers of the same chunks disagreed. One totalled a turn's usage by
coercing whatever the payload held; the other refused a payload its schema did
not accept. A malformed part therefore counted toward the composer's total and
not toward the trace's line, and a reader saw two numbers for one turn. One
reader with one rule removes the disagreement by construction, and the rule is
the one the trace already applied, so a group's line and the totals move
together.

The same argument holds for the phase: the status line and the trace group both
read `data-sub-agent-call`, and they now read it through one `readDispatch`.

# What was rejected

**Leaving the folds in the application.** Rejected: they name no application
concept. Every kind they read is a kind the wire carries, and the package
already carried a conformance test for each of them while exporting nothing to
fold them. Three of those kinds are not in the core table: `data-lead-usage`,
`data-sub-agent-call` and `data-sub-agent-step` are registered by an assistant
whose agents are a lead and its sub-agents, which section 5.2 permits, and the
readers over them stay here because a client reads a shape and not a
deployment.

**Coercing with `Number()`, so a stringified count still totals.** Rejected: it
accepts payloads no producer of this protocol emits, and it was one half of the
disagreement. A producer that sends a count as a string is broken, and reading
zero says so.

**Dropping a whole payload when one field is malformed.** Rejected: it was the
other half of the disagreement, and it hides a dispatch from the total that the
trace still draws a group for.

**Reading the lane out of a progress chunk's `id`.** Rejected: section 6.1 says
the id is an opaque reconciliation key and the lane names itself in the
payload.
