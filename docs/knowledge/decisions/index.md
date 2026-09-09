# Decisions

Choices made deliberately, each naming the alternative that was rejected and why.

## The wire

- [The wire protocol is a written spec](the-wire-protocol-is-a-written-spec.md) - PROTOCOL.md is prose a non-JS consumer implements from, and a package test captures every example from a real turn
- [Part kinds keep their names](part-kinds-keep-their-names.md) - the data-part registry opened without namespacing the kinds, because every kind string is persisted and replayed
- [A resumed stream reads one turn](a-resumed-stream-reads-one-turn.md) - the transport ends a resumed stream at the `start` that opens another turn and serves the rest to the next resume
- [siteId, mode and phase are core request fields](site-id-is-a-core-request-field.md) - the runtime carries all three unread, so they stay typed on the generic turn state
- [A registered data kind is not a protocol kind](a-registered-data-kind-is-not-a-protocol-kind.md) - every `data-` kind reaches the client, because an assistant may register kinds the document does not name
- [The readers over a message's parts belong to the client](the-part-readers-belong-to-the-client.md) - the trace, the usage totals, a task's lanes and the running phase are one fold each, read with the types the wire states

## The runtime

- [The checkpoint allowlist binds at construction](the-checkpoint-allowlist-binds-at-construction.md) - the allowlist is the argument the serializer is built with, so every decode enforces it
- [The thread carries its own messages across turns](the-thread-carries-its-own-messages-across-turns.md) - a one-agent turn runs over the checkpointed thread history, bounded by nobody
- [A tool source's session belongs to the turn](a-tool-source-session-belongs-to-the-turn.md) - the turn's driver opens and closes every declared MCP session
- [The admitted tool sources are installed by the host](admitted-tool-sources-are-installed-by-the-host.md) - admission is a value a host installs once, never a field parsed from the environment
- [The runtime's stored defaults name no product](the-runtime-defaults-name-no-product.md) - the application and assistant defaults are `default`, and a host stamps its own id
- [Input screening is configured by the host](input-screening-is-configured-by-the-host.md) - the model directory is a constructor argument, the rejection is a plain error, and the ONNX runtime is an optional extra

## Persistence

- [The runtime ships its own migration chain](the-runtime-ships-its-own-migration-chain.md) - the four tables it owns are created by an alembic history it packs, and the baseline no-ops on a database a host chain already built
- [The runtime owns its task tables](the-runtime-owns-its-task-tables.md) - `background_tasks` and `task_progress` become the runtime's, and `users` is the one table a host supplies

## Packaging

- [The client is a package with three rings](the-client-is-a-package-with-three-rings.md) - a dependency-free protocol core, one AI-SDK-coupled transport, and the legacy task dialect
- [The client scope names the organisation](the-client-scope-names-the-organisation.md) - the package publishes as `@veupathdb/assistant-client`, because the wire is not one product's
- [The conformance suite is a separate distribution](the-conformance-suite-is-a-separate-distribution.md) - the families ship inside a pip-installable plugin, and a skipped check is not a pass
- [The settings-source scaffold is written per distribution](the-settings-source-scaffold-is-written-per-distribution.md) - four copies of fifteen lines are accepted, and a fifth micro-distribution is not
- [The process logging setup is written per distribution](the-process-logging-setup-is-written-per-distribution.md) - the runtime and the MCP server each configure structlog, and the copies are reconciled by hand
- [The embedder is copied, and a host gates the drift](the-embedder-is-copied-and-a-host-gates-the-drift.md) - the two distributions may not depend on each other, so the copy stays and the application that installs both compares them
