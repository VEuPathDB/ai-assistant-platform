---
type: Backlog
title: A truncated bearer survives redaction in a check message
description: The conformance suite redacts whole credentials from a check's message, but pytest shortens long reprs before the message is built, so a truncated prefix of the bearer can appear in the report of a check that errored.
tags: [mcp-conformance, security, reporting]
generated: { by: claude-code/fable-5.1, at: 2026-09-10T00:00:00Z }
verified: { by: claude-code/fable-5.1, at: 2026-09-10T00:00:00Z }
status: open
---

# What is missing

`packages/mcp-conformance` replaces every credential it knows with a marker
before a check's message reaches the admission record. When a check errors,
pytest renders the failing frame's locals and shortens a long value with an
ellipsis before the suite sees the text, so a `ConformanceTarget.bearer` can
reach the message as its first characters followed by `...`. The redaction
matches the whole credential and does not match the truncated prefix, so the
prefix survives into the report file and the console.

A passing or failing check never renders locals, so the leak needs an errored
check; that is the state a misconfigured deployment produces most.

# What would close it

Redact by prefix as well as by whole value (any run of the bearer's leading
characters at or above a fixed length), or keep the bearer out of reprs by
holding it in a type whose `__repr__` masks it (the way `pydantic.SecretStr`
does) so pytest can render nothing to truncate. A test that errors a check on
purpose and asserts no byte of the bearer appears in the record or the captured
output.
