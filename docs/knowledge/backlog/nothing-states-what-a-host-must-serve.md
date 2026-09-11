---
type: Backlog
title: Nothing here states the transport a host must serve
description: The runtime ships no HTTP while PROTOCOL.md specifies three endpoints, and no page joins the two. A second consumer reconstructs the routes, the worker installs and the composition root by reading the one host that exists.
tags: [assistant-core, protocol, host-integration, docs]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Ran `grep -rn "fastapi\|starlette\|APIRouter" packages/assistant-core/src
packages/assistant-core/pyproject.toml`. Listed `packages/*/README.md`. Read
`PROTOCOL.md` sections 2 and 12, the root `README.md`, and
`docs/knowledge/conventions/`.

# What I got

The grep prints zero lines: the runtime imports no web framework and declares
none. `packages/assistant-client-ts/README.md` and
`packages/mcp-conformance/README.md` exist; `packages/assistant-core/README.md`
does not.

`PROTOCOL.md` section 2 specifies three endpoints:

- "**Tail.** `GET <thread>/events?after=<cursor>` streams every chunk after
  `cursor` and then follows the log live."
- "**Snapshot.** `GET <thread>/events/snapshot` returns
  `{chunks, cursor, openMessage?}` for the completed history"
- "One write is defined: `POST <api-root>/chat` starts a turn and answers with
  a tail."

The root `README.md` is 191 lines. Its "What a host supplies to the runtime"
section documents the seams in prose (quota, cancellation, authz, scratchpad,
tasks, registry, errors), and it contains the word "transport" once, at line
139: "HTTP status; a host maps them onto its own transport." It names no
endpoint, no handler and no install order.
`docs/knowledge/conventions/` holds two pages, `verification-gates.md` and
`durable-background-tasks.md`; neither names an endpoint. The readers those
routes serve are in the runtime and unmentioned by any page:
`fetch_snapshot_chunks`, `fetch_chunks_after` and `latest_turn_boundary` in
`packages/assistant-core/src/assistant_core/conversation/event_stream.py`.

# Why that is wrong

A second organisation standing up its own assistant has to write three routes
and a worker entrypoint with no statement of what they must do. The only worked
example is the one host: `pathfinder: apps/api/src/pathfinder/transport/http/routers/chat.py`,
`pathfinder: apps/api/src/pathfinder/transport/http/routers/conversations/events.py`,
the six runtime installs in one block at
`pathfinder: apps/api/src/pathfinder/jobs/worker.py` lines 54 to 60, and
`install_task_app` at `pathfinder: apps/api/src/pathfinder/jobs/app.py` line 22.
Nothing states which of those installs must run before the worker consumes its
first job, so a host that omits one learns it from a failing turn. Reading a
second repository to implement the first one's specification also copies that
repository's choices, which is how a generic runtime acquires a house style it
never agreed to.

# Why it happens

`PROTOCOL.md` states the wire and the root `README.md` states the seams, but no
page maps one onto the other: there is no host-integration convention and no
`README.md` for `assistant-core`.

# Fix

Add `docs/knowledge/conventions/embedding-the-runtime-in-a-host.md`, linked
from `docs/knowledge/conventions/index.md`, stating for each of the three
endpoints the runtime call that serves it, the order of the turn a `POST /chat`
handler runs (resolve the spec from the registry, run the identity gate, append
the user message, defer the chat-turn job, answer with a tail), the worker
installs and which must precede the first job, and the error types a host maps
onto status codes. Documentation only: it rides the next `assistant-core`
release and PathFinder changes nothing when it moves its tag from `v0.3.0a6`
(`pathfinder: apps/api/pyproject.toml`).

# What you would get

A host serves the three endpoints and starts a worker from this repository
alone, with no checkout of a consuming application.
