"""The turn log's own vocabulary: one chunk, and one message part.

A chunk is one row of the durable log, as the wire carries it. A part is one
entry of the message a reader rebuilds from those rows.
"""

from typing import Any

type Part = dict[str, Any]
type Chunk = dict[str, Any]

__all__ = ["Chunk", "Part"]
