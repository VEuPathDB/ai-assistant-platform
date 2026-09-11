---
type: Decision
title: The test process exits with pytest's status before the ONNX destructors run
description: A session-finish hook flushes the streams and leaves the process with pytest's own exit status once a run has imported the ONNX Runtime, because that runtime aborts in its static destructors at interpreter shutdown. Splitting the gate command, dropping the scanner tests and accepting a non-zero exit on a green run were all rejected.
tags: [assistant-core, testing, input-screening, gates]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: stable
---

# What was decided

The suite's `pytest_sessionfinish` hook is the outermost wrapper around the
session, so it runs after pytest wrote its summary and after every other plugin
finished. When the run imported `onnxruntime`, it flushes both streams and
calls `os._exit` with the session's own exit status. The interpreter's static
destructors never run.

Without it the run printed its count and then aborted at interpreter shutdown,
with exit 134 and

```
libc++abi: terminating due to uncaught exception of type std::__1::system_error:
recursive_mutex lock failed: Invalid argument
```

The abort follows the `onnxruntime` import and nothing else, and the ONNX
Runtime carries the defect upstream (microsoft/onnxruntime issue 24579).

Measured on one machine, eight runs per column of
`uv run pytest tests/unit -q -p no:cacheprovider`, every run green (773 passed
before the hook, 775 after, because the hook brought its own test):

| runs that exited 134 | before the hook | after the hook |
| --- | --- | --- |
| the whole unit tier | 6 / 8 | 0 / 8 |

A failing run still fails: the status the hook exits with is the one pytest
computed, so a run with one failing test leaves with 1.

# Why

A gate that exits 134 after a green summary is a flaky gate. CI reads the exit
code and not the summary line, so the abort failed the job whatever the tests
said, and a green run that fails the build is the same cost as a red one.

The scanners are the runtime's code, and the extra they need is the point of
`input-screening-is-configured-by-the-host.md`. A suite that never imports them
proves nothing about either, so the import stays and the shutdown goes.

# What was rejected

**Accepting a non-zero exit on a green run.** Rejected: the exit code is what
CI reads. A rule that asks a reader to prefer the summary line over the status
holds for a person watching a terminal and for nothing in `ci.yml`.

**Splitting the gate command so the screening tests run in their own process.**
Rejected: the gate set is written three times - `.pre-commit-config.yaml`,
`.github/workflows/ci.yml` and the package README - and a split would have to be
spelled the same in all three. A command that differs between the three is the
failure mode those three copies already have.

**Deleting the tests that import the scanners.** Rejected: it removes the only
coverage of the extra and of the Unicode scanner, to make a shutdown message go
away.

# Anchor

`packages/assistant-core/tests/conftest.py`: `pytest_sessionfinish`, declared
`wrapper=True, tryfirst=True` so that the summary is already written when it
runs. `packages/assistant-core/tests/unit/test_session_exit.py` drives a child
run that imports the runtime and asserts the code and the summary it leaves
with, so a hook that hides a failure or eats the summary fails here.
`packages/assistant-core/tests/unit/capabilities/test_piguard_import.py` keeps
its absent-package probe in a child process, because reloading a screening
package leaves its native runtime half built.
