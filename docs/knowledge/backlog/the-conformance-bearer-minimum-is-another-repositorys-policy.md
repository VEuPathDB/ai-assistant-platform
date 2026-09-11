---
type: Backlog
title: The conformance suite refuses a bearer on another repository's rule
description: BEARER_MINIMUM is 32, justified by a comment citing one tool server's token module, and no option relaxes it. A third-party server whose deployment issues a shorter bearer is refused before a session opens.
tags: [mcp-conformance, admission, generality]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Read `packages/mcp-conformance/src/mcp_conformance/_options.py` and looked for
an option or environment variable that changes the value.

# What I got

`_options.py:29-32`:

```
# The shortest secret a registry admits an application on
# (veupathdb-mcp: src/veupathdb_mcp/service_tokens.py). No deployment admits a
# shorter bearer, so the suite refuses one before it opens a session.
BEARER_MINIMUM = 32
```

The options the file defines beside it are the endpoint, the bearer, a second
bearer and `--mcp-max-call-seconds`; there is no option, and no environment
variable, that carries a different minimum. The cited module is in a different
distribution: `veupathdb-mcp: src/veupathdb_mcp/service_tokens.py`.

# Why that is wrong

The suite is the gate a deployment runs before it admits an MCP tool server,
and it is published as its own distribution so that a server nobody here wrote
can pass it. A third-party server whose operator issues, for example, a 24
character bearer is refused by `ConformanceTarget` before the first handshake,
on a length policy that belongs to one tool server's token issuer and to no
part of MCP. The operator cannot pass the gate without lengthening a secret
their own registry already considers valid, and the refusal message points at a
repository they do not have.

# Why it happens

`BEARER_MINIMUM` in `mcp_conformance/_options.py` is a constant taken from
another distribution's issuing rule and validated against every target.

# Fix

Keep a default of 32 and make it an option, `--mcp-bearer-minimum`, with the
same environment fallback the other options have, and rewrite the comment to
state the property the suite actually asserts, which is that a target is
refused a credential shorter than the deployment's own minimum. Rides the next
`veupathdb-mcp-conformance` release. PathFinder pins that distribution at
`v0.3.0a5` (`pathfinder: apps/api/pyproject.toml`) and passes no new option
when it moves the tag, because the default is unchanged.

# What you would get

A third-party tool server runs the admission suite against its own bearer
policy, and a deployment that wants the stricter minimum states it on the
command line.
