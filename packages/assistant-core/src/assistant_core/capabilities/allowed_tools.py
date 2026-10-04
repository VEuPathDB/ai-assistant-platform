"""Every function tool on every request, and a choice that lets the model call
only the tools no rule withholds, so the tool list never changes within a run."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass, replace

from pydantic_ai import RunContext
from pydantic_ai.capabilities.abstract import AbstractCapability, RawToolArgs
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.settings import ModelSettings, ToolOrOutput, merge_model_settings
from pydantic_ai.tools import ToolDefinition

type WithholdRule[DepsT] = Callable[
    [RunContext[DepsT], Sequence[str]],
    Collection[str] | Awaitable[Collection[str]],
]


@dataclass
class AllowedTools[DepsT](AbstractCapability[DepsT]):
    """Lets the model call only the function tools no rule withholds.

    A rule takes the run and the names of the tools on the request, and returns
    the names the model may not call now. OpenAI receives the full list and an
    ``allowed_tools`` choice; a provider without that choice filters the list.
    A withheld tool a model calls anyway is refused before it runs.
    """

    rules: Sequence[WithholdRule[DepsT]]

    async def _withheld(self, ctx: RunContext[DepsT], names: Sequence[str]) -> set[str]:
        withheld: set[str] = set()
        for rule in self.rules:
            found = rule(ctx, names)
            withheld.update(await found if inspect.isawaitable(found) else found)
        return withheld

    async def before_model_request(
        self,
        ctx: RunContext[DepsT],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        names = [
            t.name for t in request_context.model_request_parameters.function_tools
        ]
        withheld = await self._withheld(ctx, names)
        allowed = [name for name in names if name not in withheld]
        if len(allowed) == len(names):
            return request_context
        choice = ModelSettings(tool_choice=ToolOrOutput(function_tools=allowed))
        return replace(
            request_context,
            model_settings=merge_model_settings(request_context.model_settings, choice),
        )

    async def before_tool_validate(
        self,
        ctx: RunContext[DepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: RawToolArgs,
    ) -> RawToolArgs:
        if tool_def.kind == "output":
            return args
        if call.tool_name in await self._withheld(ctx, [call.tool_name]):
            msg = f"{call.tool_name} cannot be called now. Call a tool this request allows."
            raise ModelRetry(msg)
        return args


__all__ = ["AllowedTools", "WithholdRule"]
