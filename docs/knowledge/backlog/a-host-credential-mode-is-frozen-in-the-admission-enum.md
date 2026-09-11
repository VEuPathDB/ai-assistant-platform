---
type: Backlog
title: A VEuPathDB credential mode is a closed enum in the generic runtime
description: CredentialMode is Literal["none", "service", "veupathdb_user"] while the runtime branches only on "none" and otherwise calls the host's credential callback. A second organisation cannot name its own mode without a release.
tags: [assistant-core, mcp, admission, generality]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: open
---

# What I did

Read `packages/assistant-core/src/assistant_core/mcp/admission.py` and
`mcp/resolution.py`, then grepped the whole `packages` tree for the third
value.

# What I got

`mcp/admission.py:8`:

```
type CredentialMode = Literal["none", "service", "veupathdb_user"]
```

`grep -rn 'veupathdb_user' packages` returns six lines: that declaration and
five test fixtures (`tests/unit/mcp/test_resolution.py:319,331`,
`tests/unit/mcp/test_admission.py:152`,
`tests/integration/mcp/test_in_process_server.py:133,138`). No runtime module
reads the value. The only branch on the field is `mcp/resolution.py:135-138`:

```
    def _credential_for(self, record: AdmissionRecord) -> str | None:
        if record.credential_mode == "none":
            return None
        return self.credential(record)
```

Every mode that is not `none` takes the same path into the host's callback.

# Why that is wrong

A second organisation admitting a tool server whose credential is, say, an
institutional login has no name for it. `AdmissionRecord` is built from
operator configuration and `extra="forbid"`, so an unlisted mode is refused at
construction: the deployment cannot start until this repository cuts a release
adding one word that the runtime will then ignore. The word is also a false
signal to a reader of the enum, who reasonably expects the runtime to treat the
third mode differently from `service`, and it does not.

# Why it happens

`CredentialMode` in `mcp/admission.py` enumerates one host's credential
vocabulary, although `_credential_for` in `mcp/resolution.py` distinguishes
only `none` from everything else.

# Fix

Narrow the runtime's own vocabulary to what it reads and open the rest: type
`AdmissionRecord.credential_mode` as a non-empty `str` whose one interpreted
value is `none`, stated on the field and asserted by the suite. The host's
credential callback already receives the whole record, so it reads any mode it
defines. Rides the next `assistant-core`
release. When PathFinder takes that tag it keeps the string `veupathdb_user` in
its own admission configuration and its callback keeps matching on it; nothing
else changes.

# What you would get

A deployment admits a tool source under a credential mode it names itself, and
the runtime keeps its one meaningful branch.
