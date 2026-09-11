# assistant-platform

Three distributions and the wire between them. Nothing here knows about genes,
strategies or VEuPathDB: an assistant built on this runtime brings its own
science.

| folder | distribution | import name |
| --- | --- | --- |
| `packages/assistant-core/` | `assistant-core` | `assistant_core` |
| `packages/assistant-client-ts/` | `@veupathdb/assistant-client` | - |
| `packages/mcp-conformance/` | `veupathdb-mcp-conformance` | `mcp_conformance` |

## The `screening` extra

`assistant-core[screening]` adds the ONNX runtime and the tokenizer that
`assistant_core.capabilities.input_screening` needs. A host that screens user
text before an agent reads it declares the extra and tells the scanner which
directory holds the model; an assistant that screens nothing declares plain
`assistant-core` and carries neither wheel.

## One Yarn project, one lock

This folder is its own Yarn project: `package.json` declares
`packages/assistant-client-ts` as its only workspace, pins the Yarn release, and
`yarn.lock` here is what the client resolves against. `yarn install --immutable`
is the first step of the client's CI lane, so the suite runs against the versions
the lock names rather than whatever a fresh install picks.

A consuming application names this repository, the workspace and one release tag
(`"@veupathdb/assistant-client":
"git+https://github.com/VEuPathDB/ai-assistant-platform.git#workspace=@veupathdb/assistant-client&tag=v<version>"`).
Yarn clones the repository, installs it with its own lock, runs `prepack` and
packs `dist`, so the consumer compiles the built output and needs no install
here.

From `ai` 6.0.250 a resumed stream is seeded from empty state instead of from
the assistant message the client already holds, so the client rebuilds the
message the tail continues. `DurableChatTransport` therefore resumes a message
a turn left open from a cursor before that message's own `start`, drops what the
tail delivers before it, and opens the next tail itself where the host ended one
at a `done`. That is what section 6.1 of `PROTOCOL.md` asks of a turn suspended
on a durable task: the gap's `data-task-progress` and `data-task-completed`
chunks belong to the suspended turn's message, and a host serves them on a
second tail. The cursor a replay names comes from the store, which the snapshot
seeds from its `openMessage`, so a reload never tails from `0`. The peer range
is `>=6.0.250 <8`, the releases that seed a resume that way;
`tests/conformance/replayedMessage.test.ts` is the gate, and it fails on
`ai` 6.0.154.

## The runtime carries its own migration chain

`assistant-core` owns `conversations`, `messages`, `conversation_events`,
`memory_tombstones`, `chat_turn_cancellations`, `monthly_usage`,
`scratchpad_notes` and `scratchpad_compactions`, and ships
the alembic history that creates them under `src/assistant_core/alembic/`,
recording its position in `alembic_version_assistant_core`. A host
application's chain uses its own version table, so the two share a database
without touching each other.

```bash
uv run python -m assistant_core.migrate     # bring the runtime's tables to head
```

The runtime does not migrate at start. A host that embeds this package as a
library runs `assistant_core.migrate.upgrade_head(connection)` on its own
connection, after its own chain, because the runtime's tables name host tables
in foreign keys. A database whose host chain already created the tables a
revision would build needs no `alembic stamp`: each revision asks the inspector
first and records the position without rebuilding anything. A database holding
some of one revision's tables is refused, naming which are present and which
are missing.

`assistant_core.migrate.OWNED_TABLES` is the ten names, and
`assistant_core.migrate.include_object` is the alembic filter that keeps them. A
host whose own `env.py` maps its tables on the same declarative base uses that
filter's complement, so neither chain autogenerates a revision for the other's
tables. A revision names the tables it created in its own `CREATES`, which does
not move when the distribution grows; a test holds the union of those to
`OWNED_TABLES`.

The runtime declares one host table it does not own. A host supplies `users`
with a uuid `id`. Nothing else is read from it.

## What a host supplies to the runtime

The runtime holds the rules that read its own rows and hands back the decisions
a product makes. These seams carry that split.

`assistant_core.quota` counts spend into `monthly_usage` per user per
application, and `get_current(session, user_id, limit_usd=...)` takes the
budget as an argument: the runtime stores no limit and reads no user record.
What a caller at a hundred percent is told is the host's.

`assistant_core.conversation.cancellation` writes the stop row a running worker
polls, and fails the job of a worker that is already gone through
`assistant_core.tasks.maintenance`.

`assistant_core.conversation.authz` answers ownership over a
`ConversationLookup`, a protocol whose one member is `get_by_id`. A host passes
the thread store it already holds and inherits nothing from the runtime.

`assistant_core.scratchpad.rendering.render_scratchpad` draws a thread's note
index and appends a `ScratchpadGuidance`, three strings the host writes: what to
start noting on an empty scratchpad, what to do before the turn ends on a filled
one, and what is worth promoting to long-term memory.
`build_scratchpad_toolset(promoted_kind=..., guidance=...)` is a value a host
puts in an agent's `toolsets`; the runtime names no agent, the third string
lands on the `promote_to_memory` tool description, which is what the model
reads when it decides to promote, and `promoted_kind` is the memory kind a
promoted note is written under, because the kinds are the host's.

`assistant_core.scratchpad.compactor.compact_scratchpad` takes a factory that
builds the compactor agent, so the model and the rewriting instructions are the
host's, and a host builds one only when a ceiling is passed. The runtime owns
the gate, the token trim, the cost and the write-back.

`assistant_core.tasks` runs durable tools on a queue the host opens.
`install_task_app(app, durable_queue=...)` gives the runtime the procrastinate
application, its schema and the name of the queue durable jobs run on, which a
worker reads back from `worker_queues()`; `install_worker_context(build)` builds the turn context a durable body
reads; `install_completion_turn(run)` drives the turn a finished task opens;
`install_durable_job_context(ctx)` carries state a worker cannot re-derive, so
the runtime names no product's credential. Each of those has a `reset_*` in the
same module. A host subclasses `DurableJobState` and types every credential
`CarriedSecret`, and `register_durable_jobs` scrubs the carried state out of
the queue's own log lines, so no host filter matches on a product's key name.
`declare_durable_tool` names a tool once, and the decorator, the procrastinate
job and the worker body all read that value.
`assistant_core.tasks.heartbeat.HeartbeatThread` writes the beat that
`worker_dead_heartbeat_seconds` reads, and the settings refuse a beat too slow
for that window. `assistant_core.tasks.names` holds the queue and job
names a host wires, and `assistant_core.tasks.chat_turn` states the two fields
the stalled-job sweep reads out of a host's chat-turn payload.

`assistant_core.registry.install_assistant_registry` serves the assistants to
work that carries no request, such as the turn a finished durable task opens.

`assistant_core.errors.AssistantCoreError` is the base of every refusal the
runtime raises across that surface (`ConversationNotFoundError`,
`ConversationForbiddenError`, `TurnStillRunningError`). None of them names an
HTTP status; a host maps them onto its own transport.

## PROTOCOL.md is the contract

[`PROTOCOL.md`](packages/assistant-core/src/assistant_core/PROTOCOL.md) is the
wire an `assistant-core` deployment serves and the TypeScript client reads: the frame grammar, cursor semantics, the
snapshot and tail contract, the turn shape, the chunk vocabulary and the
reduction rules. It is versioned and additive only.

Both sides are pinned to it. `assistant-core`'s
`tests/integration/conversation/test_protocol_document.py` compares the document
against the chunks the runtime actually emits, so a new chunk kind fails there.
The client's suite is the **consumer-side gate**: `yarn sync:protocol` reads the
document into `src/protocol/captured.json`, and `tests/conformance/` fails when
the capture and the document disagree. The sync is an authoring step; the gate
is the suite that reads the capture back. A change to `PROTOCOL.md` that neither
side implements fails both.

The document ships inside the runtime package, so an installed consumer reads it
at `Path(assistant_core.__file__).parent / "PROTOCOL.md"`, the same bytes the
deployment serves. `tests/packaging` builds the wheel and reads it back.

What a host writes to serve that wire is
[embedding the runtime in a host](docs/knowledge/conventions/embedding-the-runtime-in-a-host.md):
the runtime call behind each of the three endpoints, the order a chat handler
runs, the installs a worker makes before its first job, and the refusals a host
maps onto status codes.

## mcp-conformance is an admission gate

`mcp_conformance` is the suite an MCP tool server passes before a deployment
admits it. It runs against a served endpoint
(`pytest --pyargs mcp_conformance --mcp-endpoint <url> --mcp-bearer <token>`)
and produces an admission record. It ships apart from the runtime because a
deployment reads a server it did not build.

## Gates

```bash
yarn install --immutable
cd packages/assistant-core        && uv sync --frozen && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest && uv run pytest tests/packaging -m wheel --override-ini addopts=''
cd packages/assistant-client-ts   && yarn typecheck && yarn lint && yarn format:check && yarn test && yarn build
cd packages/mcp-conformance       && uv sync --frozen && uv run ruff check src tests && uv run mypy --strict src && uv run pytest
node scripts/check-knowledge.mjs  && node --test scripts/check-knowledge.test.mjs
```

Those four lanes are what `.github/workflows/ci.yml` runs, command for command.
`.pre-commit-config.yaml` carries the same checks as hooks, and leaves the wheel
check and the integration half of the runtime suite to CI.

`assistant-core`'s suite runs with **no** application installed; that is what
makes the boundary an installation fact rather than a lint rule.

## docs/knowledge is the durable record

[`docs/knowledge/`](docs/knowledge/index.md) holds the choices behind this
repository, in Open Knowledge Format v0.2. `scripts/check-knowledge.mjs` is its
gate: every page carries a `type`, every relative link resolves, and every page
is linked from its directory's index.
