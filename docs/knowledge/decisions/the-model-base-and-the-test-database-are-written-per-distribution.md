---
type: Decision
title: The camelCase model base and the test-database bootstrap are written per distribution
description: CamelModel is written in assistant_core.platform.pydantic_base and in veupathdb.model, and the testcontainers Postgres fixture is written in each repository's own conftest. The two distributions must not depend on each other, and a third distribution for a twenty-line base class and a fixture is a dependency every consumer pays for one class, so both copies stay.
tags: [assistant-core, packaging, duplication, testing]
generated: { by: claude-code/opus-5, at: 2026-09-10T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-10T00:00:00Z }
status: stable
---

# What was decided

Two shapes are written once per distribution.

**The camelCase model base.** `CamelModel` is a `BaseModel` subclass whose whole
body is one `ConfigDict(alias_generator=to_camel, populate_by_name=True)`, plus
the docstring that forbids a per-field `alias=` on a subclass. It is written
twice:

| distribution | module |
| --- | --- |
| `assistant-core` | `assistant_core/platform/pydantic_base.py` |
| `veupathdb-py` | `veupathdb/model.py` |

The class is the same in both. The annotated number types beside it are not:
the runtime carries `RoundedFloat` and `RoundedFloat2`, and the client carries
`NonFiniteToNone` and `NonFiniteToNoneRounded`, because WDK answers `Infinity`
and `NaN` on the wire and the runtime never sees one.

**The test-database bootstrap.** A session fixture starts
`pgvector/pgvector:pg16` through `testcontainers`, hands out its connection URL
with the `asyncpg` driver, and stops it. It is written three times, in
`packages/assistant-core/tests/conftest.py`, in
`veupathdb-mcp: tests/integration/conftest.py`, and in
`pathfinder: apps/api/src/pathfinder/tests/conftest.py`. Only the image name is
shared; each copy then does what only its own repository can do. The runtime
creates its own `Base.metadata`, the tool server runs its own alembic chain to
head, and the application reuses a `DATABASE_URL` that answers and falls back to
a container when it does not.

Both duplications are accepted.

# What was rejected

**One shared package holding both.** `assistant-core` and `veupathdb-py` must
not depend on each other: the runtime serves any assistant and knows nothing
about VEuPathDB, and the client is the VEuPathDB surface. A shared package would
therefore be a third distribution, and it would arrive with a pyproject, a lock,
a release tag, a CI lane and a pin in every consuming repository. Every consumer
of the runtime would take that dependency to get one base class of about twenty
lines and a pytest fixture it does not import at runtime at all. The cost of the
shared thing is larger than the thing, as with the settings-source scaffold and
the process logging setup.

**A shared package holding the fixture alone.** A conftest fixture is not
importable surface: each copy differs in the half that matters, which is how the
schema is built. Deduplicating the four lines that name the image leaves the
other twenty in place.

**One copy in `veupathdb-py`, imported by the runtime.** This is the same edge
rejected for the settings-source scaffold, and for the same reason.

# The cost of being wrong

The failure this admits is a drift between the two `CamelModel`s. If one copy
changes its `alias_generator` or drops `populate_by_name`, the two distributions
serialize the same field to two different JSON names, and the type pipeline that
generates the TypeScript from the application's OpenAPI spec publishes whichever
name the schema that reached it carried. Nothing fails at import; a field simply
arrives under a name no consumer reads.

Nothing detects that today. The shape to copy if it ever bites is the drift gate
the application already runs over the two copies of the embedder:
`pathfinder: apps/api/src/pathfinder/tests/unit/platform/test_embedder_copies_agree.py`
parses both modules, strips the imports and the docstring, renames the
distribution-specific symbols to one placeholder, and compares the rest. An
application that installs both distributions is the only process that can run
it. See [The embedder is copied, and a host gates the drift](the-embedder-is-copied-and-a-host-gates-the-drift.md).

The bootstrap carries no such cost. A drift between two conftests is a test that
fails in one repository, in that repository's own CI, on the change that caused
it.

# Anchor

`assistant_core/platform/pydantic_base.py` and `veupathdb/model.py`. Done if the
two `CamelModel` bodies stop being the same code, or if a third distribution
needs the base and the count of copies starts to grow with the repository count.
