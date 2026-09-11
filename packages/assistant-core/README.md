# assistant-core

The assistant runtime: turns, durability, streaming, checkpoints, memory, the
scratchpad, durable background tasks and the cost count. It knows nothing about
any product's science, and it serves no HTTP.

```
pip install assistant-core          # add [screening] to screen user text
```

## What an assistant declares

`assistant_core.spec.AssistantSpec` is one assistant as the runtime sees it: the
graph it builds, the state it checkpoints, the turn context it needs, the mock
model its tests run on, the stream parts it registers, the tool sources it asks
for, the identity it requires, and the three turn hooks (`turn_prologue`,
`turn_cancel`, `turn_epilogue`). `assistant_core.registry.AssistantRegistry`
holds the assistants a deployment serves, and
`registry.resolve_turn_assistant` answers which one a turn runs under.

An assistant that is one agent needs no graph of its own:
`assistant_core.graph.single_agent.single_agent_graph` is the stock one.

## What a host writes

A host serves three endpoints, runs a worker, maps the runtime's refusals onto
its own transport, and installs the seams the runtime reads. The endpoints and
their runtime calls, the order a chat handler runs, the worker's installs and
the errors are one page:
[embedding the runtime in a host](../../docs/knowledge/conventions/embedding-the-runtime-in-a-host.md).

The wire those endpoints serve is
[`PROTOCOL.md`](src/assistant_core/PROTOCOL.md), which ships inside the package:
an installed consumer reads it at
`Path(assistant_core.__file__).parent / "PROTOCOL.md"`.

## Observability

`assistant_core.platform.metrics` holds the instruments: five `assistant.turn`
series, written by the chunk writer and the turn's message, and six
`assistant.sse` series, written by one event-stream subscription.
`install_meter_provider(provider)` names the provider they are built on, and a
process that installs none records on the global OTEL metrics API, which is a
no-op sink until something configures it.

## The tables

The runtime owns its tables and ships the alembic history that creates them.
`python -m assistant_core.migrate` brings them to head, and
`assistant_core.migrate.OWNED_TABLES` names them. One table is the host's: a
`users` table with a uuid `id`.

## Gates

```bash
uv sync --frozen
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest
uv run pytest tests/packaging -m wheel --override-ini addopts=''
```

The suite runs with no application installed, which is what makes the boundary
an installation fact rather than a lint rule. `pytest` needs a Postgres and
starts a container when `DATABASE_URL` names none.
