from __future__ import annotations

from collections.abc import Sequence

from assistant_core.embeddings.embedder import get_embedder
from assistant_core.memory.schemas import MemoryValue


async def embed_text(texts: Sequence[str]) -> list[list[float]]:
    """The vectors LangGraph's store writes and searches with.

    The store calls this once per configured ``fields`` entry per item, and
    ``fields`` names one synthetic payload key, so a memory carries one vector.
    """
    return await get_embedder().embed_documents(list(texts))


def format_embedded_string(value: MemoryValue) -> str:
    """Combined text used for a memory's embedding.

    Every field the store lists costs one vector per put, so kind, name, tags
    and summary travel in one string under a single key.
    """
    tags_joined = ", ".join(value.tags)
    return f"{value.kind} :: {value.name} :: {tags_joined} :: {value.summary}"
