# Backlog

Everything known to be outstanding in this repository, ranked. An item is
removed when it is done, not marked done: this file and the items beside it are
exactly what remains.

## Ranked

Ordered by what stands between a second organisation and its own assistant on
this runtime: first what it cannot do without forking or a release, then what
misleads whoever implements the wire, then naming.

1. [Nothing here states the transport a host must serve](nothing-states-what-a-host-must-serve.md) - the runtime serves no HTTP while `PROTOCOL.md` specifies three endpoints, and no page joins the two
2. [One host's memory kinds are frozen in the wire model](the-memory-kinds-are-frozen-in-the-wire-model.md) - `MemoryKind` is a closed five-name `Literal` while the store, the retriever and the tombstone index all take a string
3. [A VEuPathDB credential mode is a closed enum](a-host-credential-mode-is-frozen-in-the-admission-enum.md) - `CredentialMode` names a mode the runtime never branches on, and `extra="forbid"` refuses any other
4. [The conformance bearer minimum is another repository's policy](the-conformance-bearer-minimum-is-another-repositorys-policy.md) - a third-party server with a shorter bearer is refused before the handshake, with no option to relax it
5. [Two memory field descriptions carry one host's science](two-memory-field-descriptions-carry-one-hosts-science.md) - the model is coached to title and tag memories in a domain a second consumer does not work in
6. [Memory retrieval branches on site_id](memory-retrieval-branches-on-site-id.md) - the runtime drops candidates on a field its own decision page says it never reads
7. [A kind the runtime emits is absent from the data-part table](a-runtime-emitted-kind-is-absent-from-the-data-part-table.md) - `data-scratchpad-updated` is written from four runtime call sites and named nowhere in the document
8. [Three agent-topology kinds sit in the core vocabulary](three-agent-topology-kinds-sit-in-the-core-vocabulary.md) - `data-lead-usage`, `data-sub-agent-call` and `data-sub-agent-step` are core and have no runtime emitter
9. [The durable queue is named for one host's phase](the-durable-queue-is-named-for-one-hosts-phase.md) - every host's worker consumes a queue called `verification`
10. [The typed-part meta keys name one organisation](the-typed-part-meta-keys-name-one-organisation.md) - a third-party tool server must emit `org.veupathdb.assistant/...` to get a typed part or a call budget
