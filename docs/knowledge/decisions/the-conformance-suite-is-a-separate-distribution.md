---
type: Decision
title: The conformance suite is a distribution of its own, and a skipped check is not a pass
description: veupathdb-mcp-conformance is a pip-installable pytest plugin whose six families ship inside the package and run with --pyargs against a URL; it depends on mcp, httpx, pytest and pydantic and on nothing this deployment owns. Putting the families in the api test tree and putting them in assistant-core were both rejected, because the first consumer of the suite is a team whose server we did not write.
tags: [mcp, conformance, packaging, testing, admission]
generated: { by: claude-code/opus-5, at: 2026-08-25T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`packages/mcp-conformance` is its own distribution, `veupathdb-mcp-conformance`.
It declares four dependencies (`mcp<2`, `httpx`, `pytest`, `pydantic`), targets
Python 3.10 because that is the floor the `mcp` client supports, and names no
package this repository owns. A test walks every module in it and fails on an
import of `pathfinder` or `assistant_core`, and a second test fails
on any import outside the four declared distributions.

**The families ship inside the package**, as `test_shape`, `test_auth`,
`test_annotations`, `test_errors`, `test_timeouts` and `test_stability`, run
with `pytest --pyargs mcp_conformance`. A team runs the version it installed;
there is no copy of the suite to drift.

**A run is configured by URL and credential**, through options the plugin
registers (`--mcp-endpoint`, `--mcp-bearer`, `--mcp-bearer-second`,
`--mcp-bearer-minimum`, `--mcp-meta-namespace`, `--mcp-report`,
`--mcp-sample-args`, `--mcp-slow-tool`, `--mcp-isolation-tool`,
`--mcp-max-call-seconds`). The two credentials, the endpoint, the minimum and
the namespace also read environment variables, because a credential on a
command line is a credential in a shell history. The shortest bearer a target
admits is the operator's policy, not this suite's: the default is 32 and a
deployment whose registry issues another length states it.

**The report separates `incomplete` from `pass`.** A family whose checks were
skipped, and a family that did not run at all, both leave the verdict
`incomplete`. Only a run where every family ran and every check passed says
`pass`. An admission record that reads as a pass because nobody supplied a
second credential is worse than no record.

**Two checks are extension points, because their subject is the server's.**
Family 3 compares the account before and after a call, and what "the account"
is belongs to the server: the operator's harness answers the
`pytest_mcp_account_state` hook with a callable listing what the credential
holds. Family 2's isolation case needs a resource the second identity owns, so
the runner names the tool and its arguments. Neither is guessed, and neither
passes silently when it is absent.

**Every probed call is bounded by the budget the tool declares** in
`org.veupathdb.assistant/maxCallSeconds`, or by `--mcp-max-call-seconds`. A
conformance run that hangs on a slow tool reports nothing.

# What was rejected

**The families as a test module in the host application.** It is the smallest change and
the tools it would test are already there. Rejected because the suite's first
consumer is a team whose server we did not write: running it would mean
installing `pathfinder`, its database and its fixtures on their CI to test a
Java process. Our own server's run is a caller of this package, not its home.

**The suite inside `packages/assistant-core`.** The runtime already speaks MCP
and already has an admission model, so the code would sit beside what it
checks. Rejected because the runtime pins pydantic-ai, langgraph, psycopg, sqlalchemy
and openai; a Java team's CI would install all of it to read a tool list. It
would also invert the runtime's boundary suite, which exists to keep test
frameworks out of the runtime's imports.

**A container image instead of a package.** It is how the fixture account will
eventually ship. Rejected as the primary artifact because a container cannot be
composed programmatically: our own lane runs the same families in-process
against the served container, and a foreign team's CI usually has Python before
it has a Docker socket. The container remains available later; the package is
what the families live in.

**Letting a runner override a fixture.** The obvious extension point is a
`mcp_account_state` fixture the runner redefines. It was implemented and it
does not work: a fixture in the runner's `conftest.py` is invisible to tests
that live inside an installed package, and a fixture in a `-p` plugin loses to
the plugin the package installs through its entry point, because the entry
point registers later. The pytest hook is order-independent, which is why the
extension point is a hook.

# What would falsify this

`cd packages/mcp-conformance && uv run pytest` runs the suite's own tests with
no part of this deployment installed; the day one of them needs `pathfinder`,
the boundary is gone. Each family is run there against a compliant fixture
server and against a server carrying one planted defect, and the defect must
fail the check that owns it and no other: a family that cannot fail is not a
gate, and that is what those tests assert.
