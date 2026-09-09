---
type: Decision
title: The admitted tool sources are installed by the host, never parsed from the environment
description: AdmittedSources reaches the runtime through a module-level install_admitted_sources seam that a host calls once at start, the shape use_settings_source already has. Threading the admitted set through the turn seam as a parameter, and giving RuntimeSettings the endpoint list, were both rejected.
tags: [assistant-core, mcp, admission, configuration]
generated: { by: claude-code/opus-5, at: 2026-08-24T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`assistant_core/mcp/admission.py` owns `install_admitted_sources(admitted)` and
`get_admitted_sources()`. A host builds the frozen `AdmittedSources` value from
its own configuration and installs it once, at process start; the runtime reads
it where it resolves a declaration. That is the shape `use_settings_source`
already has in `assistant_core/platform/config.py`, so operator configuration
the host owns reaches the runtime one way.

The seam takes the value, not a reader callable. Settings are read per call so
a host can refresh them; the admitted set is fixed when the process starts, and
a callable would let two reads inside one turn disagree about which servers
exist.

# What was rejected

**A parameter threaded through the turn seam.** The runtime would take the
admitted set where a turn is driven, next to the declarations it resolves. It
was rejected because a parameter is a channel: admission exists to make "a
request can never name a server" true by construction, and the cheapest way to
keep that true is to have no argument a request could travel through. It also
multiplies per-turn plumbing across the app runner and the package harness for
a value that is identical on every turn of a process.

**A field on `RuntimeSettings`.** An admission record is nested and repeated:
an endpoint, a credential mode, a part namespace, an approval policy and a
call budget, per source. Flat environment variables carry that only as JSON
inside a scalar, which is configuration hiding in a string. `RuntimeSettings`
also declares `extra="ignore"`, so a misspelled variable is dropped without a
word, and a deployment would then admit nothing while believing it admitted a
server. For the one set whose whole job is to be an allowlist, a silent empty
is the wrong failure.

# The consequence, stated

A declaration naming a source the host did not install resolves to nothing, and
an unadmitted source requires approval for every call
(`pathfinder: docs/design/2026-08-23-mcp-and-sdk-program.md` section 2.2,
rule 2). A
deployment that installs no set admits nothing; site_help declares the wdk
source and runs without it when nothing is admitted, and PathFinder declares
none. A test that installs a set restores the empty one, because the seam is
process-wide by design.

# Anchor

`assistant_core/mcp/admission.py`, pinned by
`packages/assistant-core/tests/unit/mcp/test_admission.py`: a process admits
nothing until a host installs a set, installing replaces it, and no admission
field is readable from the environment through `RuntimeSettings`.
