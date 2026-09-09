"""Message-history processors an agent runs over its own run history.

The order is fixed: pairing repairs the history, elision shortens consumed
results, compaction folds the middle into one digest.
"""

from assistant_core.conversation.history.compaction import compact_history
from assistant_core.conversation.history.elision import elide_consumed
from assistant_core.conversation.history.pairing import pair_orphans

HISTORY_PROCESSORS = (
    pair_orphans,
    elide_consumed,
    compact_history,
)

__all__ = [
    "HISTORY_PROCESSORS",
    "compact_history",
    "elide_consumed",
    "pair_orphans",
]
