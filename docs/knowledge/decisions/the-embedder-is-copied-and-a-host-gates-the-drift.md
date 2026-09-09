---
type: Decision
title: The embedder is copied into two distributions, and the one host that installs both gates the drift
description: assistant_core/embeddings and veupathdb_mcp/embeddings hold the same three modules and the same 1024-dimension contract, differing only in the settings source, the error base and the import paths; neither distribution may depend on the other, so the copy stays and a test in the application that installs both compares the two constants, the four settings fields and the two stored widths, and fails when either copy moves.
tags: [assistant-core, embeddings, packaging, duplication]
generated: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-09T00:00:00Z }
status: stable
---

# What was decided

Two distributions carry the same embedder. `diff -u` over the three pairs shows
the difference is the settings source, the error base and the import paths:

| pair | difference |
| --- | --- |
| `embedder.py` | `get_runtime_settings` against `get_embedding_settings`; `EmbeddingUnavailableError` sits on `RuntimeError` against `SemanticIndexUnavailableError` |
| `openai_embedder.py` | `RuntimeSettings` against `EmbeddingSettings` in the constructor, and the two import lines |
| `fake.py` | one import line |

The batching, the character budget, the retry count and the 1024-dimension
contract are the same in both. The copy stays.

# What was rejected

**One shared module in `assistant-core`.** `veupathdb-mcp` would then depend on
the runtime, and drag `langgraph` and `pydantic-ai` into a tool server whose own
boundary suite fails on exactly those imports.

**One shared module in `veupathdb-py`.** `assistant-core` must stay site
agnostic: it serves any assistant, and the client library is the VEuPathDB
surface.

**A fifth micro-distribution for it**, as with the settings-source scaffold and
the logging setup. Rejected for the reason recorded there.

# The drift gate

An application that installs both distributions is the only process that can
compare them, so the gate lives there and not here. It reads both modules and
fails when a value moves in one copy alone.

The values compared:

- `EMBEDDING_DIMENSIONS`, which is `1024` in both.
- `REQUEST_CHAR_BUDGET` and `_MAX_RETRIES` in `openai_embedder.py`.
- The four settings fields the embedder reads: `embedding_model`,
  `embedding_batch_size`, `embedding_input_char_limit` and
  `embedding_request_concurrency`.

The files compared:

| copy | files |
| --- | --- |
| runtime | `assistant_core/embeddings/embedder.py`, `openai_embedder.py`, `fake.py` |
| tool server | `veupathdb_mcp/embeddings/embedder.py`, `openai_embedder.py`, `fake.py` |
| settings | `assistant_core/platform/config.py`, `veupathdb_mcp/embeddings/settings.py` |
| stored width | `veupathdb_mcp/alembic/versions/2026_08_29_0001_add_embedding_record_manager.py:18` and `apps/api/alembic/versions/2026_08_29_0001_add_embedding_record_manager.py:19`, both `_EMBEDDING_DIMENSIONS = 1024` |

The stored width is the row that matters most: a vector column built at one
width and an embedder that returns another is a write that fails at insert
time, and the two revisions declare the number independently.
