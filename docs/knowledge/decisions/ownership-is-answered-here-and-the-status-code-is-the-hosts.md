---
type: Decision
title: Ownership is answered here and the status code is the host's
description: A thread belongs to a user under one application, and assistant_core.conversation.authz decides that. It raises ConversationNotFoundError or ConversationForbiddenError on a small AssistantCoreError base, so the runtime never names an HTTP status.
tags: [assistant-core, authorization, tenancy, errors]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

Ownership is user plus application
(`assistant_core/persistence/models.py`), so the rule that reads it belongs
with the rows. `assistant_core.conversation.authz` holds it:

| name | what it answers |
| --- | --- |
| `owned_by_caller(conversation, user_id)` | the predicate, with no lookup |
| `get_conversation` | the thread, whoever owns it |
| `get_owned_conversation` | the caller's thread, telling a non-owner it exists |
| `get_visible_conversation` | the caller's thread, hiding it from everybody else |
| `assert_owner` | `get_visible_conversation` over a session |
| `conversation_owner_id`, `conversation_application_id`, `conversation_assistant_id` | what a worker job reads to run as the right principal |

The three lookups take a `ConversationLookup`, a protocol whose one member is
`get_by_id`. A host passes the repository it already holds, and inherits
nothing.

The two lookups differ in what a non-owner learns, and both shapes are needed:
a route that already showed the thread's existence may refuse it, and a route
that has not must not confirm the id.

The refusals are `ConversationNotFoundError` and `ConversationForbiddenError`
in `assistant_core.errors`, both on `AssistantCoreError`. Each carries the
`conversation_id` it refused. A host maps them onto its own transport.

# What was rejected

**Raising an HTTP-shaped error.** The application these functions came from
raised a type carrying a status, a title and a product error code. The runtime
serves no HTTP and knows no error-code enum, so an error of that shape would
either drag a wire vocabulary into the runtime or make every host adopt one.

**Deriving the runtime's base from the client library's error base.** The
runtime may not depend on the WDK client distribution, so a shared base would
have to be a fourth distribution for one class.

**Typing the lookups against the concrete repository.** That would make a host
subclass the runtime's repository to be accepted, and every listing the host
adds with a different return type would be a Liskov break in waiting. The
helpers read one method, so the parameter states one method.

**One lookup with a boolean for the refusal.** A flag at the call site is read
by whoever changes the route last. Two named functions state which one a route
means, and the difference is the docstring rather than the argument.

# Anchor

`packages/assistant-core/tests/unit/conversation/test_authz_application_scope.py`:
the owner reaches the thread, the same user under another application is told
nothing, another user under this application is told nothing, the forbidding
helper separates missing from not-yours, and the error names the id it refused.
