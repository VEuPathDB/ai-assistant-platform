# Log

## 2026-09-09

The scratchpad moved in whole: `assistant_core.scratchpad` holds the note
models, the ids, the notebook that opens one session per call, the nine tools,
the toolset that hides what an empty scratchpad cannot use and breaks a read
streak, the rendered index and the compaction run.
`assistant_core.persistence.repositories.scratchpad.ScratchpadRepository` owns
the rows, including the fork copy and the revert cut, so a host never writes a
statement against the runtime's tables. `scratchpad_notes` and
`scratchpad_compactions` joined the chain as revision `2026_09_09_0003`, and
`OWNED_TABLES` is eight names.

Two seams keep the product out. `render_scratchpad` takes a
`ScratchpadGuidance` of two strings, so what the model is told to write down is
the host's sentence and the runtime's default is empty. `compact_scratchpad`
takes the compactor agent, so no model id and no rewriting instruction lives
here; the runtime keeps the gate, the input rendering, the token trim, the cost
and the transaction. A failed compaction run now reaches the caller instead of
being swallowed twice.

The tools no longer name another distribution's tool-error type: a turn with no
thread returns `ScratchpadUnavailable`, the same three fields under the same
`NOT_FOUND` code. `data-scratchpad-updated` is unchanged; the runtime already
built that chunk and now owns what emits it.

Two decisions are new: the scratchpad is the runtime's and the coaching is the
host's; the compactor agent is supplied by the host.

The scratchpad seams took their review round:

- `ScratchpadGuidance` carries a third string, `promote`.
  `build_scratchpad_toolset(guidance=...)` appends it to the description of
  `promote_to_memory`, which is the text the model reads when it decides what
  is worth keeping. An empty string appends nothing.
- `compact_scratchpad` takes a factory for the compactor agent rather than a
  built one, and calls it once after both ceilings are read. A host builds an
  agent per compaction, not per turn.
- The read-streak filter is private again as `_read_tools_to_hide`. Its only
  caller is the toolset's own prepare step, and the behaviour is proved through
  the tools a turn is offered.

The runtime took the budget, the ownership rule and the stop protocol.
`assistant_core.quota` counts spend per user per application into
`monthly_usage` and reports a period snapshot against a limit the caller
supplies; `assistant_core.pricing` reads one headline price pair from the
packaged snapshot, at an instant the caller may name. `assistant_core.conversation.authz` answers ownership as
user plus application, over a `ConversationLookup` protocol whose one member is
`get_by_id`. The generic `ConversationRepository` that creates, reads, lists,
renames, dismisses, restores and deletes a thread satisfies it, and so does a
host's own store.
`assistant_core.conversation.cancellation` writes the stop row the running
worker polls, and takes `release_dead_turn` from the host because the runtime
owns no job queue. The refusals are `AssistantCoreError` subclasses in
`assistant_core.errors`, so no HTTP status is named here.

`chat_turn_cancellations` and `monthly_usage` joined the chain as revision
`2026_09_09_0002`, which no-ops on a database whose host chain built both and
refuses one that holds only one of them. `OWNED_TABLES` is six names now, and
each revision freezes the tables it created in its own `CREATES`, so the two
stay reconciled by a test rather than by one shared literal that history would
have to follow.

Three decisions are new: the runtime counts the cost and the host sets the
limit; ownership is answered here and the status code is the host's; a stop is
a row and the host releases the job.

The runtime got a migration chain of its own: `assistant_core/alembic/`,
the version table `alembic_version_assistant_core`, and
`assistant_core.migrate.upgrade_head(connection)` for a host that runs it
beside its own on one connection. The baseline asks the inspector before it
builds, so a database whose host chain already created all four tables is
stamped by running the chain rather than by hand; a database holding some of
them is refused by name, and the baseline never downgrades. `OWNED_TABLES` and
`include_object` in `assistant_core.migrate` are the four names and the
autogenerate filter that keeps a host's tables out of this chain's revisions.

Three decisions are new: the runtime ships its own migration chain; the
runtime owns its task tables and `users` is its one host-table contract
(proposed, executed when the task subsystem moves); the embedder is copied
into two distributions and the one host that installs both gates the drift.

The client is `@veupathdb/assistant-client` 0.3.0-alpha.1. Four readers the
consuming application held moved into it: the turn and thread usage fold, one
durable task's lifecycle and its lanes, the running phase of a dispatch, and
the AI SDK part conversion `toTraceParts`. The core ring exports them beside
`isToolPart`, `isDataPart`, `readSubAgentStep`, `PartLike` and `MessageLike`,
and `./ai-sdk` exports `toTraceParts`. The tool-summary status list is one
exported constant the reducer, the trace and the SDK fold all read.

Two usage rules are reconciled on the library's reading: a count whose type
the wire does not state reads as nothing spent, and a dispatch that names no
phase counts toward the turn's total. `runningPhase` sits in
`core/dispatch.ts` beside the payload reader the trace uses, rather than
inside `core/trace.ts`, which the package's line cap refuses.
`isKnownChunkKind` stays permissive for every `data-` kind: gating it on the
captured list drops the kinds an assistant registers.

Three decisions are new: the client scope names the organisation; the part
readers belong to the client; a registered data kind is not a protocol kind.

## 2026-09-08

Input screening arrived: `assistant_core/capabilities/piguard.py` and
`assistant_core/capabilities/input_screening.py`, with the model directory as a
constructor argument, `ScreeningRejectionError` in place of an HTTP-shaped
error, and the ONNX runtime behind the `screening` extra. `setup_logging` now
assigns its handler onto the root logger, so a second call leaves one handler.
Two decisions are new: input screening is configured by the host; the process
logging setup is written once per served distribution.


Bundle created. The runtime, protocol, client and conformance decisions that had
been living in the consuming application's bundle moved here, and their
`verified` stamps were refreshed against the code as it stands today. Three
decisions are new: `site_id`, `mode` and `phase` are core request fields;
the runtime's stored defaults name no product; the settings-source scaffold is
written once per distribution.

`conventions/verification-gates.md` carries the three package gate sets, which
had been three sections of the consuming application's own gates page.

PROTOCOL 1.7.1: the product-extension table of section 12.2 is empty and the
request examples carry a neutral site, mode and tool name.
