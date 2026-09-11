# Backlog

Everything known to be outstanding in this repository, ranked. An item is
removed when it is done, not marked done: this file and the items beside it are
exactly what remains.

## Ranked

Ordered by what stands between a second organisation and its own assistant on
this runtime: first what it cannot do without forking or a release, then what
misleads whoever implements the wire, then naming.

1. [Nothing here states the transport a host must serve](nothing-states-what-a-host-must-serve.md) - the runtime serves no HTTP while `PROTOCOL.md` specifies three endpoints, and no page joins the two
2. [A kind the runtime emits is absent from the data-part table](a-runtime-emitted-kind-is-absent-from-the-data-part-table.md) - `data-scratchpad-updated` is written from four runtime call sites and named nowhere in the document
3. [Three agent-topology kinds sit in the core vocabulary](three-agent-topology-kinds-sit-in-the-core-vocabulary.md) - `data-lead-usage`, `data-sub-agent-call` and `data-sub-agent-step` are core and have no runtime emitter
4. [The typed-part meta keys name one organisation](the-typed-part-meta-keys-name-one-organisation.md) - a third-party tool server must emit `org.veupathdb.assistant/...` to get a typed part or a call budget
