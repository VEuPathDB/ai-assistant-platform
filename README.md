# assistant-platform

Three distributions and the wire between them. Nothing here knows about genes,
strategies or VEuPathDB: an assistant built on this runtime brings its own
science.

| folder | distribution | import name |
| --- | --- | --- |
| `packages/assistant-core/` | `assistant-core` | `assistant_core` |
| `packages/assistant-client-ts/` | `@pathfinder/assistant-client` | - |
| `packages/mcp-conformance/` | `veupathdb-mcp-conformance` | `mcp_conformance` |

## One Yarn project, one lock

This folder is its own Yarn project: `package.json` declares
`packages/assistant-client-ts` as its only workspace, pins the Yarn release, and
`yarn.lock` here is what the client resolves against. `yarn install --immutable`
is the first step of the client's CI lane, so the suite runs against the versions
the lock names rather than whatever a fresh install picks.

A consuming application names this repository, the workspace and one commit
(`"@pathfinder/assistant-client":
"git+https://github.com/VEuPathDB/ai-assistant-platform.git#workspace=@pathfinder/assistant-client&commit=<sha>"`).
Yarn clones the repository, installs it with its own lock, runs `prepack` and
packs `dist`, so the consumer compiles the built output and needs no install
here.

`ai` is pinned to `6.0.154` and the peer range stops below `6.0.250`. That
release changed `resumeStream` so a resumed stream is a fresh response instead of
a continuation of the assistant message the client already holds, which is the
opposite of what section 6.1 of `PROTOCOL.md` requires of a turn suspended on a
durable task: the gap's `data-task-progress` and `data-task-completed` chunks
belong to the suspended turn's message. Under `ai` 6.0.271 two
`tests/conformance/resumedTurn.test.ts` cases fail for exactly that reason.

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
the capture and the document disagree. A change to `PROTOCOL.md` that neither
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
cd packages/assistant-core        && uv sync --frozen && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src && uv run pytest tests/unit
cd packages/assistant-client-ts   && yarn typecheck && yarn lint && yarn format:check && yarn test && yarn build && yarn sync:protocol
cd packages/mcp-conformance       && uv sync --frozen && uv run ruff check src tests && uv run mypy --strict src && uv run pytest
```

`.github/workflows/ci.yml` runs those three lanes and
`.pre-commit-config.yaml` carries them as hooks.

`assistant-core`'s suite runs with **no** application installed; that is what
makes the boundary an installation fact rather than a lint rule.
