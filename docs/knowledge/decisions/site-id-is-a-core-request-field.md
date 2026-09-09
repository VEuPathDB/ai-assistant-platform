---
type: Decision
title: siteId, mode and phase are core request fields, not leaked product concepts
description: TurnState.site_id, TurnState.mode and ParkedCall.phase stay on the generic turn state because PROTOCOL.md declares all three in the core request table and the runtime carries them to the assistant unread. Moving them into a per-assistant extension bag, and renaming site_id to a neutral tenant word, were both rejected.
tags: [assistant-core, protocol, turns, graph]
generated: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`assistant_core/graph/turn_state.py` keeps `TurnState.site_id`, `TurnState.mode`
and `ParkedCall.phase` as typed fields of the generic turn state. All three are
core request fields in `PROTOCOL.md` section 12.2, which states what the runtime
does with them: it carries them to the assistant and reads none of them. A
value the runtime never branches on is not a concept the runtime holds.

`site_id` names the data host a turn runs against. It is a VEuPathDB notion in
a runtime that knows nothing else about VEuPathDB, and it is core anyway,
because a deployment that serves several data hosts needs the turn to say which
one it ran against and the log to keep that answer. `mode` and the role names
that key `phaseModels` and `phaseReasoning` belong to the assistant in the same
way: the runtime passes the string, the assistant refuses one it does not know
with a `422`. The label vocabulary a reader shows for a role lives in the host
(`pathfinder: apps/web/src/lib/models/phaseRoles.ts`).

# What was rejected

**An untyped extension bag on the turn state.** Every product field would move
into one `dict[str, JsonValue]`, and the runtime would name none of them. It
was rejected because a checkpointed field with no type is a field no allowlist
can declare and no test can pin: the three fields are on the checkpoint, and
the serde allowlist works from declared types.

**Renaming `site_id` to a neutral tenant word.** A rename buys the appearance
of neutrality and costs the protocol a name a client already sends, every
stored chunk that carries it, and a major version under section 10's rule. The
field is core; a synonym would not make it less VEuPathDB-shaped.

# Anchor

`assistant_core/graph/turn_state.py` and `PROTOCOL.md` section 12.2. Done if
the runtime ever branches on one of the three: that is the day the field stops
being a value the assistant owns.
