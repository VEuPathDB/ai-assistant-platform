"""The hook the graph runs before a turn's agent.

State the assistant checkpointed can be out of date by the time the next turn
starts, because something outside the conversation changed it. The product
refreshes what it owns here and returns the state the turn runs on.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from assistant_core.graph.runtime import TurnContext
from assistant_core.graph.turn_state import TurnState

type PreTurnHook[StateT: TurnState, ContextT: TurnContext] = Callable[
    [StateT, ContextT],
    Awaitable[StateT],
]
