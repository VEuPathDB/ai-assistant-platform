---
type: Decision
title: The client package is named for the organisation, not for one consumer
description: packages/assistant-client-ts publishes @veupathdb/assistant-client. The old scope named one application, inside a repository whose other two distributions are named for the platform, so every consumer of the wire had to depend on a scope belonging to a product it does not run.
tags: [assistant-client, packaging, protocol]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

The client publishes as `@veupathdb/assistant-client` from version
`0.3.0-alpha.1`. The three entry points (`.`, `./ai-sdk`, `./legacy`) keep their
paths, and nothing else about the artifact changes.

A consumer names the workspace by that name, so the pin and the name move
together:

```
"@veupathdb/assistant-client": git+https://github.com/VEuPathDB/ai-assistant-platform.git#workspace=@veupathdb/assistant-client&tag=v<version>
```

# Why

This repository holds three distributions. Two of them (`assistant-core`,
`veupathdb-mcp-conformance`) are named for the platform and the organisation
that runs it. The client was named for the first application built on the
protocol, so a second consumer would install a package scoped to a product it
does not use, and a reader of `package.json` would take the wire protocol for
one application's internal API.

A scope is also a claim: publishing under `@veupathdb` is one this organisation
can make about every package in this repository, which is not true of a scope
named after one of its applications.

# What was rejected

**Keeping the old name.** Rejected: it makes the protocol read as one
product's, which is the opposite of what `PROTOCOL.md` claims.

**A scoped alias that resolves to the old name.** Rejected: two names for one
artifact, and Yarn resolves a workspace by name, so the alias would be a second
workspace or a second manifest.

**Renaming at 0.2.x.** Rejected: a name is the identity a consumer installs, so
the change takes a minor version of its own. The version moves to
`0.3.0-alpha.1` with it.
