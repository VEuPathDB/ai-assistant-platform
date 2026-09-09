---
type: Decision
title: The settings-source scaffold is written once per distribution, four times over
description: Each distribution carries its own _SettingsSource class plus a use_*_settings_source and get_* pair, about fifteen lines each. Extracting them into a shared module is impossible for assistant-core, which cannot depend on the client, and a fifth micro-distribution for thirty lines fails YAGNI.
tags: [assistant-core, configuration, packaging, duplication]
generated: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

Four distributions each carry their own copy of the same shape: a private
`_SettingsSource` holding one reader callable, a module-level instance, a
`use_*_settings_source(read)` that replaces the reader, and a `get_*()` that
calls it.

| distribution | module |
| --- | --- |
| `assistant-core` | `assistant_core/platform/config.py` |
| `veupathdb-py` | `veupathdb/settings.py` |
| `veupathdb-mcp` | `veupathdb_mcp/settings.py` |
| `veupathdb-mcp` | `veupathdb_mcp/embeddings/settings.py` |

The duplication is accepted. Each copy is about fifteen lines, is typed against
its own settings model, and never changes once written.

# What was rejected

**One shared implementation in `veupathdb-py`.** It is the distribution the two
VEuPathDB packages already depend on. It was rejected because `assistant-core`
must not depend on it: the runtime knows nothing about VEuPathDB, and its
package-boundary suite is an installation fact, not a lint rule.

**A fifth micro-distribution holding the scaffold.** Thirty lines of code would
arrive with a pyproject, a lock, a release tag, a CI lane and a pin in four
other repositories, and every one of those four would then release whenever the
scaffold moved. The cost of the shared thing is larger than the thing.

**A generic base class parameterised by the settings type.** It removes the
class body and keeps the module-level instance, the installer and the reader in
every distribution, so it deduplicates about five lines of the fifteen and adds
a generic to each call site.

# Anchor

The four modules above. Done if a fifth distribution needs the shape and the
count of copies starts to grow with the repository count rather than staying at
one per settings model.
