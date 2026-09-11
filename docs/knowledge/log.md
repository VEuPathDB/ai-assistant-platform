# Log

## 2026-09-11

`assistant_core.platform.pydantic_base` publishes `computed`, a computed field
a type checker reads as the value it computes. A `@computed_field` stacked on
`@property` is a decorated property, which mypy refuses and which reads as a
bound method without the `@property`; `computed` wraps the property itself, so
the attribute is typed as its value under both checkers and serializes like a
field. `assistant-core` is 0.3.0a6.

## 2026-09-10

Three backlog items are closed and the backlog is empty. A tool source an
assistant declares as optional and the deployment does not admit is now
reported once, at INFO, naming the source id the deployment admits by. The set
that answers the question remembers what it has already said is absent, so a
host that installs one set for the process reads one line however many turns
resolve it, whatever local names the assistants gave that source; a source
declared required keeps its warning and its refusal on every turn. `assistant-core` is 0.3.0a5.

The conformance suite holds its credentials in `SecretStr`. A check that errors
renders a mask where pytest used to shorten the value, so there is nothing for
a report to match on, and `redact` now takes out every run of a credential
sixteen characters or longer, wherever in the text it sits, so a shortened
value cannot carry one either. Sixteen is half the shortest secret a deployment
admits, so a run that long is the credential and not prose, and the suite's own
name survives a report. The suite refuses a bearer shorter than that secret
before it opens a session, because no deployment could admit one, and an empty
option reads as no bearer at all. `__version__` reads the distribution's own number
instead of a second literal that had already drifted from it.
`veupathdb-mcp-conformance` is 0.1.2.

`scripts/check-knowledge.mjs` resolves a citation of another repository. A
prefix names a checkout beside this one, a path that checkout does not have
fails, and a citation is reported as unverified when there is no checkout to
read. A citation written without the space after the colon fails on its form
rather than passing unread. Three repositories share the script and its test; `ai-wdk-mcp` carries
neither a bundle nor a scripts directory.

The last two duplications the placement sweep left are decided rather than
removed. `CamelModel` stays written in `assistant_core/platform/pydantic_base.py`
and in `veupathdb/model.py`, and the testcontainers Postgres fixture stays
written in each repository's own conftest: the two distributions may not depend
on each other, and a third distribution for a twenty-line base class and a test
fixture is a pin, a tag and a CI lane every consumer pays for one class. One
decision is new: the camelCase model base and the test-database bootstrap are
written per distribution. It records what a drift between the two `CamelModel`s
would cost, and names the embedder drift gate the consuming application already
runs as the shape to copy if that ever happens.

## 2026-09-09

The durable-task subsystem moved in whole. `assistant_core.tasks` holds the
`@durable_tool` decorator, the declaration registry, the payload, the progress
emitter, the runner, the completion turn, the task service and read queries,
and the stalled-job release. `background_tasks` and `task_progress` joined the
chain as revision `2026_09_09_0004`, `OWNED_TABLES` is ten names, and the
host-table contract is now `users` alone. The baseline no longer creates
`conversation_events.task_id`'s foreign key; the fourth revision adds it after
creating the table it points at.

`procrastinate` is a dependency of this package, and the application it runs on
is not: a host builds it and calls `install_task_app`. Three more seams carry
what the runtime cannot know: `install_worker_context` builds the turn context
a body reads, `install_completion_turn` drives the turn a finished task opens,
and `install_durable_job_context` carries state the worker cannot re-derive, so
no product's credential is named here. `assistant_core.tasks.names` declares
the queues and the two job names a host wires.

The three strings that had to match became one value.
`declare_durable_tool` returns a `DurableTool`; the decorator and the body
registration take it, and `register_durable_jobs` derives the procrastinate
job. A registration naming an undeclared tool is refused at import with a
sentence that says what to pass.

`release_dead_turn` came with the queue, so the `release_dead_turn` argument
of `stop_turns_and_wait`, `stop_turn_before_delete` and `cancel_active_turn` is
gone; a stop releases the job itself. `assistant_core.registry` grew
`install_assistant_registry`, because the completion turn resolves a thread's
assistant with no request to read one from.

Nothing on the wire changed. `data-background-task-started`,
`data-task-progress` and `data-task-completed` are built by the same three
functions, the coalescing rule is five percentage points or ten seconds, the
suspended turn still ends with `finishReason: "other"`, and
`assistant-client-ts`'s `durableTask.test.ts` passes unchanged.

Two decisions are new: the runtime defers onto the host's queue; a durable tool
is declared once. `The runtime owns its task tables` is stable, and the
durable-task convention this bundle now carries came from the consuming
application's own instructions.

The credential a host carries onto a worker is now typed. `DurableJobState` is
the model a host subclasses, `CarriedSecret` is the field type that masks
itself in a repr, and `install_job_payload_redaction` keeps the value out of
the queue's own log lines, so no host filter matches on a product's key name;
it names the worker's own logger and `setup_logging` attaches it again, so
neither call order leaves the line unscrubbed.
The heartbeat moved with the window that reads it:
`assistant_core.tasks.heartbeat` writes the beat, `RuntimeSettings` carries
`worker_heartbeat_interval_seconds` and refuses a beat too slow for
`worker_dead_heartbeat_seconds`. Each installed seam grew a `reset_*` in its
own module, so a test installs and resets through the public surface.
`assistant_core.tasks.chat_turn` publishes the two fields the stalled-job
sweep reads out of a host's chat-turn payload.

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
