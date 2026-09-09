---
type: Decision
title: A one-agent turn runs over the thread's own messages, carried on the checkpoint and bounded by nobody
description: TurnState.thread_messages_json holds the thread's pydantic-ai messages, written by the agent node from the run's own result and trimmed to the last complete exchange; the one-agent graph reads it as message_history. Rebuilding the history from the durable chunk log, and a runtime window or summarizer over it, were both rejected.
tags: [assistant-core, graph, conversations, checkpointing]
generated: { by: claude-code/opus-5, at: 2026-08-27T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`TurnState.thread_messages_json` carries the thread's own pydantic-ai messages
between turns. The agent node of `single_agent_graph` writes it from
`result.all_messages()` when the run reports a result, and `_turn_for` reads it
back as the run's `message_history` for every turn that is not answering a
parked approval. The codec is `ModelMessagesTypeAdapter`, which is what a
parked approval already uses for the run it resumes, so one serialization
serves both. The field is a `str`, so the checkpoint allowlist that every
assistant shares needs no new type.

The thread carries whole exchanges: `settled_history` drops trailing messages
until the last one is a `ModelResponse` that pydantic-ai accepts a new prompt
over, which means no tool calls and a state other than `suspended` - the two
tails `UserPromptNode` refuses. A run that stops on
an approval therefore leaves the parked call out of the thread, because
pydantic-ai refuses a new prompt over a history that holds an unprocessed call
(`_agent_graph.UserPromptNode`), and the card's own resume history holds that
call anyway. The cost is that a card the user abandons by typing something else
takes its own turn out of the thread; a card the user answers keeps everything,
because the resumed run's messages settle and are written back. A turn that produced no result at all - cancelled, or stopped by
the repetition guard - leaves the thread where the last settled turn left it.

The carried history is not bounded. Every turn of a thread pays for every turn
before it, and that is accepted until a measurement says otherwise.

# What was rejected

**Rebuilding the history from `conversation_events`.** The durable log already
holds every turn, so a turn could read the log and reconstruct the messages.
It was rejected because the log holds AI SDK v6 chunks, not model messages: the
reconstruction is a second translator, running in the opposite direction from
`vercel_adapter`, and it has to invent what the wire does not carry - which
tool call each result belongs to as pydantic-ai pairs them, retry prompts,
instructions, and the parts a renderer dropped. A wrong pairing there is a
provider error on the next turn, not a rendering defect.

**A state class of its own for the one-agent graph.** The field could live on a
subclass that only assistants running `single_agent_graph` adopt, which would
keep it off `PipelineState`, whose cross-turn context is typed and whose own
raw message trace was deleted for that reason. It was rejected because the
stock graph is generic over `StateT: TurnState` and site help runs it on the
bare `TurnState`: a subclass makes every one-agent assistant declare a state
type, and a new checkpoint type, to get the behavior the graph already needs.
PathFinder's state inherits an empty string and its Lead never writes it.

**A window or a summarizer in the runtime.** The runtime could keep the last N
turns, or a token budget, or fold older turns into a summary. It was rejected
because no assistant has yet measured a thread that costs too much, and a bound
chosen without that measurement is a guess that silently drops what a user
said. pydantic-ai already offers the bound as `history_processors` on the agent
itself, which is where an assistant that measures the cost declares it, and
`assistant_core.conversation.history` ships the processors it declares. A
runtime window would apply one policy to every assistant, including the ones
whose threads are three turns long.
