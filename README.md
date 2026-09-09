# assistant-platform

Three distributions and the wire between them. Nothing here knows about genes,
strategies or VEuPathDB: an assistant built on this runtime brings its own
science.

| folder | distribution | import name |
| --- | --- | --- |
| `packages/assistant-core/` | `assistant-core` | `assistant_core` |
| `packages/assistant-client-ts/` | `@pathfinder/assistant-client` | - |
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
(`"@pathfinder/assistant-client":
"git+https://github.com/VEuPathDB/ai-assistant-platform.git#workspace=@pathfinder/assistant-client&tag=v<version>"`).
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
