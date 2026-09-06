# The assistant runtime wire protocol

**Version 1.6.0.** This document specifies the bytes a client exchanges with an
assistant built on `assistant_core`. It is written so a consumer in any
language can implement a client from this page alone, with no reference to the
JavaScript SDK that inspired the chunk vocabulary. Section 14 records what each
version added.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be interpreted
as described in RFC 2119.

Every example below is captured from a real turn by
`tests/integration/conversation/test_protocol_document.py`, which fails when
the runtime's output and this page disagree. Generated identifiers read as
`00000000-0000-0000-0000-000000000000` and generated instants as
`2026-01-01T00:00:00Z`; nothing else is edited.

## 1. Model

A **thread** is an ordered, append-only log of **chunks**. A **turn** is the
slice of that log between a `start` chunk and the `done` chunk that terminates
it. Every chunk row carries a monotonically increasing integer **cursor**, and
a client resumes by naming the last cursor it saw.

The log is the source of truth for what the assistant said. A client MUST be
able to rebuild the full conversation from the log alone; nothing the user sees
is carried only by a live connection.

One message id names one message. A rebuilt conversation therefore holds each
id once, and a client that meets an id twice in a log MUST keep the first
message that id names rather than refuse the thread.

## 2. Transport

An event stream MUST be served as `text/event-stream`. The runtime's own
streams also carry `x-vercel-ai-ui-message-stream: v1`, which names the chunk
vocabulary in section 5.

Two reads are defined:

- **Tail.** `GET <thread>/events?after=<cursor>` streams every chunk after
  `cursor` and then follows the log live. `after` defaults to `0`, which means
  the whole thread.
- **Snapshot.** `GET <thread>/events/snapshot` returns `{chunks, cursor}` for
  the completed history: every chunk up to and including the most recent turn
  terminator, plus the prompt that opened an in-flight turn when one exists.

The runtime guarantees that a snapshot followed by a tail from the snapshot's
cursor yields exactly the chunks a reader would have seen live, in the same
order, with the same bytes.

One write is defined: `POST <api-root>/chat` starts a turn and answers with a
tail. The thread is named in the body, not in the path. Section 12 specifies
that body, the identity a request must prove, and how the response relates to
the two reads.

## 3. Framing

A frame is a sequence of lines terminated by a blank line. Two frame shapes
are defined and a client MUST reject any third shape.

**Event frame.** Exactly two lines:

```
id: <cursor>\n
data: <payload>\n
\n
```

`<cursor>` is a decimal integer. `<payload>` is either a JSON object with no
embedded newline, or the literal `[DONE]`.

**Comment frame.** One line beginning with a colon:

```
: keep-alive\n
\n
```

A comment frame carries no cursor and no payload. The runtime sends one after
every interval of silence (15 seconds by default) so an idle stream is not
closed by an intermediary. A client MUST ignore comment frames and MUST NOT
advance its cursor on one.

## 4. Cursors and resumption

- Cursors MUST be strictly increasing within a thread. They are not dense: a
  client MUST NOT assume `n + 1` is the next cursor.
- Cursors are per-deployment, not per-thread. Two threads written at the same
  time interleave their cursors and never share one.
- `after` is exclusive. A reader that saw cursor `n` and reconnects with
  `after=n` receives the chunk after `n` and never repeats one.
- A client SHOULD persist the last cursor it observed for each thread and send
  it on reconnect. A client that has lost its cursor MUST take a snapshot
  rather than tailing from `0` mid-turn, because a tail from `0` replays parts
  the client may already hold.

A host MAY answer a tail request with `204 No Content` when the thread has no
turn in flight. A client that receives it MUST fall back to the snapshot. A
client that cannot hold a long-lived connection MAY poll the snapshot instead;
the ordering and the bytes are identical either way.

## 5. Chunk vocabulary

A chunk is a JSON object whose `type` field discriminates it. Field names are
camelCase. A field the runtime has nothing to say about is omitted, never sent
as `null`. A client MUST ignore a chunk whose `type` it does not know, and MUST
ignore unknown fields on a chunk it does know.

### 5.1 Stream chunks

<!-- chunks:begin -->

| Kind | Meaning |
| --- | --- |
| `start` | The turn begins. `messageId` names the assistant message it builds. |
| `start-step` | A step of the turn begins. |
| `text-start` | A text part begins. `id` identifies the part. |
| `text-delta` | More text for the part named by `id`. |
| `text-end` | The text part named by `id` is complete. |
| `reasoning-start` | A reasoning part begins. |
| `reasoning-delta` | More reasoning text for the part named by `id`. |
| `reasoning-end` | The reasoning part named by `id` is complete. |
| `tool-input-start` | A tool call begins. `toolCallId` identifies it. |
| `tool-input-delta` | More raw input text for the call. |
| `tool-input-available` | The call's input is complete and valid. |
| `tool-input-error` | The call's input could not be parsed. |
| `tool-approval-request` | The call needs the user's approval before it runs. |
| `tool-output-available` | The call returned. |
| `tool-output-error` | The call failed. |
| `tool-output-denied` | The user refused the call. |
| `file` | A file the assistant produced. |
| `source-url` | A web source the assistant cited. |
| `source-document` | A document source the assistant cited. |
| `message-metadata` | Metadata to merge onto the assistant message. |
| `finish-step` | The step ends. |
| `error` | The turn hit an error. The turn is not necessarily over. |
| `abort` | The run was aborted. |
| `finish` | The turn ends. `finishReason` says how. |
| `done` | The turn's terminator. Its payload is the literal `[DONE]`. |

<!-- chunks:end -->

### 5.2 Data parts

A data part is a chunk whose `type` begins with `data-` and whose `data` field
carries the payload. A data part with `transient: true` MUST NOT be persisted
onto the message a client renders from history; it is a live indicator only. A
data part with an `id` reconciles: a later chunk with the same `type` and `id`
replaces the payload of the earlier one rather than appending a second part.

The runtime defines these. An assistant MAY register more.

<!-- data_parts:begin -->

| Kind | Meaning |
| --- | --- |
| `data-turn-status` | A human-readable hint about what the turn is doing. |
| `data-turn-usage` | Running tokens and cost for the turn. Transient. |
| `data-turn-stopped` | The user stopped this turn. |
| `data-turn-failed` | This turn ended in a failure. Carries the failure's text. |
| `data-lead-usage` | Usage of the lead agent alone, with the fill of its context window. Reconciles on its `id`. |
| `data-sub-agent-call` | One sub-agent dispatch, with the fill of its context window. Reconciles on its `id`. |
| `data-sub-agent-step` | One event inside a sub-agent's run. |
| `data-conversation-title` | The thread's generated title. |
| `data-background-task-started` | A durable tool was deferred to a worker. |
| `data-task-progress` | Progress of a durable tool. |
| `data-task-completed` | A durable tool finished. |
| `data-tool-summary` | One line saying what a tool call did. Patches the call's part. |

<!-- data_parts:end -->

### 5.3 Log envelopes

Three kinds are written to the log and MUST NOT be framed onto the wire. They
record the prompt side of a thread so a snapshot can rebuild the whole
conversation, and a client reads them from the snapshot's `chunks` array.

<!-- envelopes:begin -->

| Kind | Meaning |
| --- | --- |
| `user-message` | The user's message, as a complete message object. |
| `system-message` | A system message, as a complete message object. |
| `assistant-message` | A whole assistant message, not built from deltas. |

<!-- envelopes:end -->

## 6. The shape of a turn

A turn MUST begin with exactly one `start` chunk and MUST end with exactly one
`finish` chunk followed by exactly one `done` chunk. A client MAY treat `done`
as the only reliable turn boundary.

`finishReason` reports how the turn ended:

| Value | Meaning |
| --- | --- |
| `stop` | The turn ran to completion. |
| `error` | The turn's driver raised. |
| `other` | The turn was stopped by the user, or suspended on a durable task. |

An `error` chunk does not end a turn: the runtime converts a failure inside the
agent's stream into an `error` chunk, continues, and still closes the turn with
`finish` and `done`. A turn that streamed an `error` chunk and then completed
therefore reports `finishReason: "stop"`. A client MUST use the `error` chunk,
not `finishReason`, to decide whether to show a failure.

A stopped turn writes `data-turn-stopped` before `finish`, so the stopped state
survives a reload.

A turn whose driver failed writes `data-turn-failed` beside the `error` chunk,
carrying the same text, before `finish`. The `error` chunk stays the live
signal a client shows while the turn streams; the part is its durable
footprint, because the reduction rules of section 9 keep the part and keep no
trace of the `error` chunk.

A turn that ends with `finishReason: "error"` MUST first close every tool call
it left open: one `tool-output-error` per call whose input was announced and
whose result never arrived, carrying the same text as the `error` chunk. A
client therefore never renders a running tool call inside a finished turn.

A data part that carries a state of its own is not closed that way. The
runtime writes `data-sub-agent-call` with `state: "started"` when a dispatch
begins and reconciles it on its `id` when the dispatch ends, so a turn that is
stopped, or killed inside the dispatch, leaves `started` as the last payload
the log holds for it. Closing it is a reader rule: when a turn ends, a client
MUST read every dispatch that turn left `started` as **cancelled** if the turn
carries `data-turn-stopped`, as **failed** if it carries `data-turn-failed`,
and as **superseded** otherwise. Superseded says the dispatch outlived its
turn: work suspended on a durable task (section 6.1) resumes in a later turn,
whose own `data-sub-agent-call` reconciles the part and states how it really
ended. A client MUST NOT show a dispatch of a turn that is over as running,
and MUST NOT show a call inside a cancelled or failed dispatch as running
either: the turn ended before the call reported, so the call has no result
and never will. A superseded dispatch is the exception, because its work is
still running where the turn left it.

A text or reasoning part that would stay empty is never written: the runtime
holds a `text-start` or `reasoning-start` until the first delta with the same
`id` arrives, and drops the start and its end together when the end arrives
first. A reader therefore never receives a part that carries nothing, and a
model that emits a reasoning item with an empty summary before every tool call
does not cut a turn's work into pieces.

### 6.1 A turn suspended on a durable task

An assistant MAY hand a long-running tool to a worker and suspend the turn. The
turn closes normally, with `finishReason: "other"`, and the work continues
after `done`. The whole lifecycle is on the thread, so a client that reads the
log needs no second channel:

<!-- task_lifecycle:begin -->

| Chunk | Where it lands |
| --- | --- |
| `data-background-task-started` | inside the suspending turn, before its `finish` |
| `data-task-progress` | after that turn's `done`, in the gap before the next turn |
| `data-task-completed` | after the last progress, before the next turn's `start` |

<!-- task_lifecycle:end -->

The assistant's continuation is a new turn: it opens its own `start`, carries
the tool's result, and closes with its own `finish` and `done`.

Chunks in the gap belong to no turn. A client MUST accept a chunk that arrives
outside a turn and MUST NOT treat it as a malformed stream. A tail ends at the
`done` it reads, so a client that wants live progress reconnects with `after`
set to that `done`'s cursor; a snapshot taken while the task runs reports the
completed history and not the gap, and a snapshot taken afterwards holds the
whole sequence.

`data-task-progress` carries the task id as its `id`, suffixed with `:` and a
**lane** when the task runs several sequences at once - a parameter sweep's
variants, for example. The reconciliation rule of section 5.2 therefore
collapses one lane's progress into one part, and a task of five lanes leaves
five parts on the message, each advancing on its own. A task that runs one
sequence carries the bare task id and leaves one part.

A client MUST NOT read the lane out of the `id`, which is an opaque
reconciliation key: the lane names itself in the payload's `toolSpecific`, and
a producer names it there whenever it suffixes an `id`.
`data-background-task-started` and `data-task-completed` carry no `id`: each is
emitted once per task, whatever its lanes.

A reducer that splits the log at each `start` chunk therefore attaches the
gap's chunks to the message that started the task, which is where a reader
expects to see the task's card, its progress and its outcome.

**Progress is coalesced.** The log records a task's progress coarsely, because
it is replayed on every read of the thread for the life of the conversation.
An update reaches the log when it is the first for its task, when the task has
advanced five percentage points since the last one written, or when the last
one written is ten seconds old. The final update before the task ends is always
written. A host MAY offer a finer channel beside the log; section 13 specifies
the one this deployment serves.

`data-task-completed` reports whether the tool produced a result. A resumed
turn that then fails reports that failure itself, through an `error` chunk.

**One turn may suspend on several tasks.** A model step that calls two durable
tools writes one `data-background-task-started` per task before its `finish`,
and the gap then carries each task's progress and outcome as that task reports
it, in whatever order the tasks finish. The continuation is still one turn, and
it opens after the LAST of those tasks completed: it answers every call the
step made, because the run it re-enters owes a result for each of them. A
client MUST NOT read a `data-task-completed` as the end of the gap, and MUST
NOT expect the next `start` to follow it.

### 6.2 A turn suspended on an approval

An assistant MAY mark a tool as one the user must approve. The call is
announced and then stops: the turn carries `tool-input-start`,
`tool-input-available` and `tool-approval-request` for that `toolCallId`, and
closes with `finish` and `done`. The tool has not run.

The thread now holds the suspended call. The next turn carries the user's
answer, in the body section 12.3 defines, and re-enters the same call: it
carries `tool-input-available` for that same `toolCallId`, then
`tool-output-available` when the user approved and `tool-output-denied` when
the user refused. No second `tool-input-start` precedes it, because the call
was announced by the turn that suspended: a client MUST treat
`tool-input-available` as opening a call whether or not a start came before
it. The input repeats because a client that lost its history still needs the
call announced before its outcome; a client that holds the part patches it by
`toolCallId` under the rule of section 9 and appends nothing.

A turn that answers nothing - a new user message while a call waits - drops
the suspended call rather than running it. Nothing further is emitted for that
`toolCallId`, and the part stays in `approval-requested`.

### 6.3 A tool that says what it did

A tool MAY carry one line of prose describing its own result. The line rides a
`data-tool-summary` chunk naming the call:

    { "type": "data-tool-summary",
      "data": { "toolCallId": "call_a1",
                "summary": "6 of 12 Sample",
                "status": "ok" } }

The chunk MAY precede or follow that call's `tool-output-available`,
`tool-output-error` or `tool-output-denied`, in the same turn. A reducer
addresses the summary by `toolCallId`, so the order does not matter. At most one
summary per call reaches the log; a later one replaces an earlier one under the
rule of section 9. A durable tool emits its summary before its output chunk, and
that is conforming.

`summary` is one line: no newline, at most 120 characters, and never the call's
output re-serialised. `status` is `ok`, `empty` or `warn` and defaults to `ok`.
`empty` says the call succeeded and found nothing, which a client SHOULD show
differently from a call that found something, because a silent zero otherwise
reads as a success.

A failed call carries no `status`: its part is already in `output-error`.

## 7. Producer envelope

Between a turn's graph and the log, a chunk travels wrapped:

```json
{ "chunk": { "type": "text-delta", "id": "...", "delta": "..." } }
```

This envelope is internal to a deployment. It is unwrapped before the chunk is
written to the log, so it never reaches a client. It is specified here because
an assistant that emits its own chunks MUST use it.

## 8. Captured examples

One example per chunk kind the reference assistant produces. The kinds in
section 5 that are absent here are defined by the protocol and emitted by
assistants that use those capabilities; the reference assistant does not.

<!-- examples:begin -->

#### `data-tool-summary`

```json
{
  "type": "data-tool-summary",
  "data": {
    "status": "ok",
    "summary": "2 plus 3 is 5",
    "toolCallId": "call_add"
  }
}
```

#### `data-turn-status`

```json
{
  "type": "data-turn-status",
  "data": {
    "label": "Preparing context",
    "waitingOnLlm": false
  }
}
```

#### `data-turn-stopped`

```json
{
  "type": "data-turn-stopped",
  "data": {}
}
```

#### `data-turn-usage`

```json
{
  "type": "data-turn-usage",
  "data": {
    "costUsd": "0",
    "totalTokens": 57
  },
  "transient": true
}
```

#### `done`

```json
"[DONE]"
```

#### `finish`

```json
{
  "type": "finish",
  "finishReason": "stop"
}
```

#### `finish-step`

```json
{
  "type": "finish-step"
}
```

#### `message-metadata`

```json
{
  "type": "message-metadata",
  "messageMetadata": {
    "pydantic_ai": {
      "timestamp": "2026-01-01T00:00:00Z"
    }
  }
}
```

#### `start`

```json
{
  "type": "start",
  "messageId": "00000000-0000-0000-0000-000000000000"
}
```

#### `start-step`

```json
{
  "type": "start-step"
}
```

#### `text-delta`

```json
{
  "type": "text-delta",
  "delta": "You said: which sites do you serve",
  "id": "00000000-0000-0000-0000-000000000000"
}
```

#### `text-end`

```json
{
  "type": "text-end",
  "id": "00000000-0000-0000-0000-000000000000"
}
```

#### `text-start`

```json
{
  "type": "text-start",
  "id": "00000000-0000-0000-0000-000000000000"
}
```

#### `tool-approval-request`

```json
{
  "type": "tool-approval-request",
  "approvalId": "call_wipe",
  "toolCallId": "call_wipe"
}
```

#### `tool-input-available`

```json
{
  "type": "tool-input-available",
  "toolCallId": "call_add",
  "toolName": "add",
  "input": {
    "a": 2,
    "b": 3
  }
}
```

#### `tool-input-delta`

```json
{
  "type": "tool-input-delta",
  "toolCallId": "call_add",
  "inputTextDelta": "{\"a\":2,\"b\":3}"
}
```

#### `tool-input-start`

```json
{
  "type": "tool-input-start",
  "toolCallId": "call_add",
  "toolName": "add"
}
```

#### `tool-output-available`

```json
{
  "type": "tool-output-available",
  "toolCallId": "call_add",
  "output": 5
}
```

<!-- examples:end -->

## 9. Building a message from chunks

A client reduces a turn's chunks into one assistant message with an ordered
`parts` array. The rules a conforming reducer MUST follow:

- `start` opens the message it names. A reader MUST NOT carry a part it built
  for one message into the next one a `start` opens, whether the two arrive
  on one connection or on two. `message-metadata` and `finish` merge metadata.
- `start-step` appends a `step-start` part.
- `text-start` appends a text part in state `streaming`; `text-delta` appends
  to the part with the same `id`; `text-end` moves it to `done`. Reasoning
  parts follow the same rule.
- Tool chunks address one part by `toolCallId`. The part's `state` walks
  `input-streaming` -> `input-available` -> (`approval-requested`) ->
  `output-available` | `output-error` | `output-denied`. A later chunk for a
  call already in the array patches that part; it never appends a second one.
- `data-tool-summary` addresses the tool part named by `data.toolCallId`. It
  sets that part's `summary` and `summaryStatus` and appends no part. A summary
  naming a call the client does not hold is ignored.
- A non-transient data part appends, unless it carries an `id` that matches an
  existing part of the same `type`, in which case it replaces that part's
  `data`.
- A chunk that addresses a part the client does not hold MUST be ignored, not
  treated as an error.

The runtime's own reducer is `assistant_core.conversation.ui_message_reducer`.

## 10. Versioning

This protocol follows the runtime package's contract rule:

- **Additive only within a minor version.** A new chunk kind, a new data part
  or a new optional field is a minor bump. A client written against 1.0.0 MUST
  keep working against any 1.x.
- **Removing or retyping anything is a major version**, and every registered
  assistant must be migrated in the same change.
- A client MUST ignore what it does not recognise, which is what makes the
  additive rule safe.

## 11. What this contract does not cover

Channels a deployment serves beside the log are not part of this contract. The
one this deployment serves is specified in section 13, because it exists and a
consumer will meet it.

## 12. Starting a turn

A turn begins with one `POST <api-root>/chat`. The request names the thread in
its body, carries the message that opens the turn, and answers with a tail of
the log. A thread that does not exist yet is created by the first turn sent to
it, so there is no separate call to open one.

### 12.1 Identity

A request MUST carry one of:

- `Authorization: Bearer <token>`, or
- the host's session cookie.

A cookie-authenticated request that is not a `GET`, `HEAD` or `OPTIONS` MUST
also carry a non-empty `X-Requested-With` header, and is refused with `403`
without it. A browser sets neither that header cross-origin nor an
`Authorization` header, so a forged request can carry neither. A request that
carries a bearer token is exempt, because it was not sent by a browser's
ambient credential. Which bearers a deployment accepts, and how it maps one to
a user, is the deployment's business; this protocol requires only that the
request prove an identity.

### 12.2 The body

The body is JSON. Every field below is camelCase, and a field with nothing to
say is omitted.

**Core fields.** Any assistant on this runtime accepts these.

<!-- request_core:begin -->

| Field | Type | Meaning |
| --- | --- | --- |
| `conversationId` | uuid | The thread this turn belongs to. Required. |
| `id` | string | The client's id for this request. |
| `trigger` | `submit-message` \| `regenerate-message` | Why the turn is starting. Defaults to `submit-message`. Any other value is refused. |
| `messages` | array | The thread as the client holds it. The last entry opens the turn. |
| `assistantId` | string | Which assistant answers. Read only when the thread is created. |
| `siteId` | string | The data host this turn runs against. |
| `mode` | string | The assistant's own mode for this turn. |
| `phaseModels` | object | Model id per agent role, as the assistant names its roles. |
| `phaseReasoning` | object | Reasoning effort per agent role. |

<!-- request_core:end -->

`phaseModels` and `phaseReasoning` are core because the runtime carries them to
the assistant unread. The role names that key them, and the model ids a
deployment admits, belong to the assistant: a key or an id it does not know is
refused with `422`.

An entry in `messages` may carry the turn facts section 6 attaches to an
assistant message (`errors`, `aborted`, `finishReason`), and a tool part in
it may carry the stream-recorded `resultProviderMetadata` and the `summary` and
`summaryStatus` section 9 folds onto the call: a client that rehydrated its
thread from the snapshot sends them back verbatim, and the runtime MUST ignore
them rather than refuse the turn.

**Product extensions.** Fields this deployment's assistant adds. A client for
another assistant does not send them, and this runtime ignores what it does not
define.

<!-- request_extensions:begin -->

| Field | Type | Meaning |
| --- | --- | --- |
| `experimentId` | string | The PathFinder experiment this thread records against. |

<!-- request_extensions:end -->

**Messages.** Each entry is `{id, role, parts}` with `role` one of `system`,
`user` or `assistant`, and `parts` an array of typed parts. A text part is
`{"type": "text", "text": "..."}`. The last entry's `id` becomes the id of the
log row the runtime writes for it, so it MUST be a uuid.

### 12.3 What the last message means

`trigger` names the client's intent and is recorded, not branched on. What the
turn does is decided by the last entry in `messages`.

A normal turn ends `messages` with a `user` message. The runtime persists that
message, writes it to the log as a `user-message` envelope, and starts the
turn. It writes that envelope once per id: a request that ends at a message the
log already holds, which is what a regenerate sends, starts its turn and adds
no second envelope.

An approval answer ends `messages` with an `assistant` message instead: the one
that carries the tool part in state `approval-responded`, whose `approval`
object holds `{id, approved, reason?}`. The runtime reads the answers out of
the body, persists no new user message, and resumes the deferred call inside
the turn the checkpoint already holds. A client MUST NOT invent a user message
to carry an approval.

### 12.4 What the POST answers

The response is a tail, framed exactly as section 3 defines and headed
`text/event-stream`. It begins at the last turn terminator the thread held when
the request arrived, so a client reads the turn it just started from its first
chunk, and never mid-way through a prior turn.

The turn is not the connection. The runtime drives the turn to completion
whether or not the client is still reading, so a client that drops the response
loses nothing: it reconnects with the tail of section 2 from the last cursor it
saw. A client that cannot hold the response at all MAY discard it and poll the
snapshot.

### 12.5 Refusals

| Status | When |
| --- | --- |
| `401` | The request proves no identity, or the one it proves is refused. |
| `403` | A cookie-authenticated write carries no `X-Requested-With`. |
| `404` | `assistantId` names an assistant this deployment does not serve. |
| `409` | `assistantId` names an assistant other than the one the thread was created with. |
| `422` | The body does not validate, including a `phaseModels` value the assistant does not admit. |
| `429` | A deployment-level budget for this caller is exhausted. |

A thread keeps one assistant for its whole life, so replaying it always runs
the same architecture. `409` says the caller is acting on a thread whose shape
it does not know; the fix is to read the thread's assistant, not to retry.

### 12.6 Captured examples

<!-- request_examples:begin -->

#### `submit-message`

```json
{
  "conversationId": "3f1a6f4e-2c3b-4d5e-8a7b-9c0d1e2f3a4b",
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "trigger": "submit-message",
  "siteId": "plasmodb",
  "mode": "strategy",
  "messages": [
    {
      "id": "b1d0f6b2-7d0e-4a1e-9f3c-1a2b3c4d5e6f",
      "role": "user",
      "parts": [{ "type": "text", "text": "which sites do you serve" }]
    }
  ]
}
```

#### `approval-response`

```json
{
  "conversationId": "3f1a6f4e-2c3b-4d5e-8a7b-9c0d1e2f3a4b",
  "id": "1b4e28ba-2fa1-11d2-883f-0016d3cca427",
  "trigger": "submit-message",
  "siteId": "plasmodb",
  "messages": [
    {
      "id": "b1d0f6b2-7d0e-4a1e-9f3c-1a2b3c4d5e6f",
      "role": "user",
      "parts": [{ "type": "text", "text": "clear the strategy" }]
    },
    {
      "id": "c2e1a7c3-8e1f-4b2f-a04d-2b3c4d5e6f70",
      "role": "assistant",
      "parts": [
        {
          "type": "tool-clear_strategy",
          "toolCallId": "call_clear",
          "state": "approval-responded",
          "input": {},
          "approval": {
            "id": "approval_clear",
            "approved": true
          }
        }
      ]
    }
  ]
}
```

<!-- request_examples:end -->

## 13. Legacy channels

A deployment MAY serve a channel beside the log. One exists, it predates this
document, and it is specified here so a consumer that meets it can read it.
**It is deprecated.** Everything it carries is on the thread as of 1.1.0, and a
client SHOULD read the thread instead.

**Per-task progress.** `GET <thread>/tasks/<task_id>/events` streams one
durable task's progress at the rate the worker records it, rather than at the
coalesced rate of section 6.1. It is served as `text/event-stream` and it does
not carry `x-vercel-ai-ui-message-stream`.

Its frames are not the frames of section 3. Each is `event: stream` followed by
`data: <json>`, and the payload wraps the chunk in an envelope of its own:

- `{"type": "custom", "kind": "<chunk kind>", "data": {...}}` for a chunk,
- `{"type": "done", "reason": "completed" | "error"}` to end the stream.

There is no `id` line, so the stream carries no cursor and nothing on it can be
resumed. On connect it replays the task's whole progress history and then
follows it live, ending when the task reaches a terminal status.

Two payloads differ from their logged counterparts. `data-task-progress` sends
`toolSpecific: null` where the log omits the field, and `data-task-completed`
reports the task row's own status, so a tool that produced a result and then
failed to resume reads as `failed` here and as `success` on the thread.

<!-- legacy_frames:begin -->

```text
event: stream
data: {"type":"custom","kind":"data-task-progress","data":{"taskId":"00000000-0000-0000-0000-000000000000","percent":0.25,"message":"loading data","toolSpecific":{"step":"a"}}}

event: stream
data: {"type":"custom","kind":"data-task-completed","data":{"taskId":"00000000-0000-0000-0000-000000000000","status":"success","error":null}}

event: stream
data: {"type":"done","reason":"completed"}

```

<!-- legacy_frames:end -->

## 14. Changelog

<!-- changelog:begin -->

| Version | What it added |
| --- | --- |
| `1.6.0` | `data-lead-usage` and `data-sub-agent-call` carry `contextTokens` and `contextWindow`: the input size of the agent's latest request, and the model's context window. Both are optional and 0 means unknown. Before this the parts carried cumulative `tokens` only, so a client could not show how full an agent's window was, and history the runtime sheds mid-run was invisible. |
| `1.5.3` | Section 6.1 states what a turn suspended on several durable tasks emits: one `data-background-task-started` per task, each task's progress and outcome in the gap in completion order, and one continuation turn after the last outcome. Before this the section read as one task per suspension, so a client could take the first `data-task-completed` for the end of the gap. |
| `1.5.2` | Section 9 states that `start` opens the message it names and that a reader carries no part across it. Before this the rule was only implied by section 6.1, and a reader that builds one message per connection copied a suspended turn's parts into the continuation turn that follows it in the same tail. |
| `1.5.1` | Section 6 states how a reader closes a dispatch its turn left open: `cancelled` under `data-turn-stopped`, `failed` under `data-turn-failed`, `superseded` otherwise, and the calls inside a cancelled or failed dispatch are closed with it. Before this a stopped turn's `data-sub-agent-call` stayed `started` for the life of the thread, because nothing the graph writes after a stop reaches the log. |
| `1.5.0` | A `data-task-progress` `id` may name a lane inside the task (section 6.1), so a fan-out leaves one part per lane instead of one part the lanes overwrite in turn. Section 6.2 states the resume sequence the runtime emits: the resumed turn repeats `tool-input-available` alone, with no second `tool-input-start`, so a client opens a call on the input chunk. |
| `1.4.1` | Section 6: a text or reasoning part that would stay empty is never written; a start followed by its end with no delta between them is dropped whole. Before this a model's empty reasoning items reached the log as empty parts. |
| `1.4.0` | `data-tool-summary` (sections 5.2, 6.3, 9): a tool may carry one line saying what its call did, so a reader sees the work without the call's JSON. Before this the only description of a call on the wire was its raw input and its raw output. A resent tool part may carry the folded `summary` and `summaryStatus`, and the runtime ignores them (section 12.2). |
| `1.3.1` | A turn that ends with `finishReason: "error"` closes its open tool calls with `tool-output-error` first (section 6). Before this a turn killed inside a tool left the call with an input and no result, and a client rendered it as still running inside a turn that had finished. |
| `1.3.0` | `data-turn-failed`, written beside the `error` chunk of a turn whose driver failed (section 6). The `error` chunk leaves no part behind, so before this a reloaded thread showed a truncated answer with nothing saying the turn died. |
| `1.2.2` | A request's `messages` may carry the section 6 turn facts (`errors`, `aborted`, `finishReason`) on an assistant entry, and `resultProviderMetadata` on a tool part; the runtime ignores them instead of refusing the turn, so a thread rehydrated from the snapshot can keep talking. |
| `1.2.1` | The repetition guard's refusal is ordinary `tool-output-available` output, never `tool-output-error` and never a model retry: a retry raised by the guard shares the tool's retry budget and could abort a run whose tool had already retried once. The `tool-output-error` example is removed because no reference turn produces the kind; the kind itself remains in the chunk table. |
| `1.2.0` | The approval cycle a turn really runs (section 6.2): the reference assistant now emits `tool-approval-request` where it used to emit an `error`. |
| `1.1.0` | The request side (section 12), the durable-task lifecycle on the thread (section 6.1), and the legacy per-task channel written down (section 13). |
| `1.0.0` | The first specification: framing, cursors, the chunk vocabulary, the turn's shape and the reduction rules. |

<!-- changelog:end -->
