---
type: Convention
title: Verification gates
description: The exact commands that decide whether a change to one of this repository's three distributions is done.
tags: [testing, ci, workflow]
generated: { by: claude-code/opus-5, at: 2026-08-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

Gates passing is necessary, not sufficient. These are the commands, and
`.github/workflows/ci.yml` runs them command for command.
`.pre-commit-config.yaml` carries the same checks as hooks, and leaves the
wheel check and the integration half of the runtime suite to CI.

# Assistant runtime (`packages/assistant-core`)

```
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest
uv run pytest tests/packaging -m wheel --override-ini addopts=''
```

Run these from the package root, in the package's own environment. No host
application is installed there, and that is the point: the suite passing is the
boundary, not a linter rule about it. `ruff` and the tests cover `tests/` too,
because the synthetic assistant lives there and is the runtime's reference
producer.

`uv sync --frozen` installs the `screening` extra, because the dev group names
it: the boundary suite imports every module and
`assistant_core.capabilities.piguard` reads the ONNX runtime. A host that
screens no input declares `assistant-core` without the extra.

`pytest` needs a Postgres. It starts a `pgvector/pgvector:pg16` testcontainer
unless `DATABASE_URL` names one, and the conversation suite drives real
LISTEN/NOTIFY, so an in-memory substitute will not do.

`PROTOCOL.md` is gated by the suite: a chunk kind, a data part or an example
that changes without the page changing fails
`tests/integration/conversation/test_protocol_document.py`.

# Assistant client (`packages/assistant-client-ts`)

```
yarn typecheck
yarn lint
yarn format:check
yarn test
yarn build
```

Run these from the package root, after `yarn install --immutable` at the
repository root. The suite is the protocol's consumer side, so a `PROTOCOL.md`
change fails it until `yarn sync:protocol` regenerates the vendored capture and
a reducer answers the new kind.

`yarn build` is a gate because it is what `prepack` runs: every host installs
the packed `dist`, so a build that fails here is a package nobody can consume.

# MCP conformance suite (`packages/mcp-conformance`)

```
uv run ruff check src tests
uv run mypy --strict src
uv run pytest
```

Run these from the package root, in its own environment. Nothing of any
deployment is installed there, and a test walks every module to keep it that
way: the suite is run by teams whose servers we did not write.

`pytest` starts fixture MCP servers on loopback ports and drives the shipped
families at them in a child pytest, once against a compliant server and once
per planted defect. A defect must fail the check that owns it and no other. No
database, no credential and no network beyond loopback.

The families themselves are not part of this gate. They run against a server:
`pytest --pyargs mcp_conformance --mcp-endpoint <url> --mcp-bearer <token>`,
and the report they write is what an operator reads before admitting a source.

# The knowledge bundle

```
node scripts/check-knowledge.mjs
node --test scripts/check-knowledge.test.mjs
```

Run these from the repository root. The first checks this bundle against Open
Knowledge Format v0.2; the second checks the checker against its fixtures.
