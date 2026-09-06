"""The agent a turn runs.

The graph is built with a factory rather than an agent, so the agent, its
tools and any per-turn model override belong to one turn.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent

type TurnAgentFactory[AgentT: Agent[Any, Any]] = Callable[[], AgentT]
