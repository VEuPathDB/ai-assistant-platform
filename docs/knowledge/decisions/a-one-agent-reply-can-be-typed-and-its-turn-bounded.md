---
type: Decision
title: A one-agent reply can be typed, and its turn can be bounded
description: single_agent_graph takes a SingleAgent that carries the agent factory, the deps builder, optional UsageLimits and an optional TypedReply. A typed reply runs as the output type, the model's own text and its output tool never reach the client, and the node writes the text the host renders from the accepted reply. A run stopped at a limit ends on the emitter's error chunk and keeps the thread where it was. Streaming the reply's arguments, an agent-declared output type, two more graph arguments, matching the output tool by its default name and a turn-failed part were rejected.
tags: [assistant-core, graph, streaming, output, usage]
generated: { by: claude-code/opus-5-5, at: 2026-10-22T00:00:00Z }
verified: { by: claude-code/opus-5-5, at: 2026-10-22T00:00:00Z }
status: stable
---

# What was decided

`single_agent_graph` takes one `SingleAgent` value beside the checkpointer, the
two types and the usage charger. It holds `build_agent`, `build_deps`,
`usage_limits` and `reply`. Without the last two, a turn runs as it did before:
`output_type=[str, DeferredToolRequests]` and pydantic-ai's default limits.

**A typed reply.** `TypedReply(output_type=..., text=...)` names a pydantic
model and the function that renders one instance, with the turn's deps, as the
turn's text. The run's output type is `[reply.output_type,
DeferredToolRequests]`. The emitter streams an output-tool call as tool chunks,
so the agent node drops every `tool-input-*` and `tool-output-*` chunk of a call
to the reply's output tool, for a refused call and for the accepted one. It also
drops every `text-*` chunk the model streams, because that text passes no check:
under a typed reply the only text the client sees is the accepted reply's. The
node reads the output tool names from the run itself, through the
`prepare_output_tools` hook of a capability it adds to the run. When the run
ends on a reply, the node writes `reply.text(output, deps)` as one
`text-start`, `text-delta`, `text-end` group, inside the run's last step. A
reply that a check refuses never reaches the client in any chunk.

A check on the reply is a capability hook, `after_output_validate`, that raises
`ModelRetry`. pydantic-ai refuses a run-time `output_type` on an agent that
declares an `output_validator` (`Agent._prepare_output_schema` raises
`UserError`), and the graph sets the output type at run time.

The thread history carries a typed reply. A finished run ends on the output
tool's call and its return, so `settled_history` accepts a tail where every call
of the last response has a `ToolReturnPart` in the request after it.
pydantic-ai accepts a new prompt over that tail.

**Usage limits.** `usage_limits` goes to `run_stream_events`. A run that passes
a limit raises `UsageLimitExceeded` inside the event stream, and the emitter
answers it with its `error` chunk, which names the limit. The run reports no
result, so the thread history stays where the last settled turn left it. The
usage object the run counted into is the one the node charges, so
`charge_usage` receives what the stopped run spent. No `data-turn-failed` part
is written: that part belongs to a turn no worker finished.

# What was rejected

**Streaming the reply's prose from the output tool's arguments.** The reply
could reach the client as it streams, like a text answer. It was rejected
because the arguments stream before the check runs: a reply the check refuses
would already be on the client.

**Letting the agent declare its own output type.** The graph could run the
agent with the output type it was built with, so an `output_validator` on the
agent works. It was rejected because the graph renders the reply, and it must
know the type it renders: an agent built with another output type hands
`reply.text` a value it was not written for, and the failure shows only on the
first turn.

**Two more keyword arguments on `single_agent_graph`.** The limits and the
reply could be arguments of their own. It was rejected because the function
already takes six, the limit the runtime's lint holds, and the four values that
describe the agent's run belong together.

**Matching the output tool by its default name.** `final_result` is the name
pydantic-ai gives a single output type. It was rejected because the name is
pydantic-ai's and changes with the output spec: a union gets one suffixed tool
per member.

**A `data-turn-failed` part on a limit stop.** It was rejected because the
emitter's `error` chunk already ends the message with the reason, and the part
is the sweep's notice for a turn whose worker stopped.
