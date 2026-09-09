---
type: Decision
title: The runtime's stored defaults are "default", and a host stamps its own id
description: DEFAULT_APPLICATION_ID and DEFAULT_ASSISTANT_ID are "default", so a second deployment's rows are not stamped with the first deployment's name. A host sets its own application id explicitly at every write, which is why the change ships with no data migration in the runtime.
tags: [assistant-core, persistence, tenancy, defaults]
generated: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`assistant_core/platform/context.py::DEFAULT_APPLICATION_ID` and
`assistant_core/persistence/models.py::DEFAULT_ASSISTANT_ID` are both
`"default"`. The first is the value `calling_application()` answers when no
application is set and the `server_default` of every `application_id` column;
the second is the Python and stored default of `conversations.assistant_id`.

Ownership is user plus application
(`assistant_core/persistence/models.py`), so the default decides who owns a row
written by a caller that named no application. A runtime whose default is one
product's name stamps every such row with that name, in every deployment.

A host that cares which application owns its rows sets the id itself: it
installs its own value on `application_id_ctx` for the request or the job, and
it names the assistant when it creates a thread. The registry's default
assistant is already host-supplied (`assistant_core/registry.py`, `default_id`),
so nothing about routing depends on the constant.

# What was rejected

**Keeping one product's name as the runtime default.** It is the value that was
there, and no deployment breaks on the day it changes if the host stamps its own
id. It was rejected because it makes a second deployment's rows read as the
first deployment's, and because the runtime would be asserting a product it does
not know.

**Shipping the change with a data migration in the runtime.** The runtime owns
no alembic chain, and the rows are the host's: a migration that rewrote them
would decide, for a host, which application its history belongs to. The host
owns that decision, and a host whose existing rows carry its own id keeps them
visible by continuing to stamp that id.

# Anchor

`packages/assistant-core/tests/unit/test_runtime_defaults.py`: the two
constants, the value `calling_application()` answers with nothing set, and the
two stored column defaults.
