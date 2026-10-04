"""The provider-correct model settings for a ``provider:model`` id.

A provider the table does not name is refused rather than served another
provider's flags.
"""

from typing import Any

from pydantic_ai.models.anthropic import AnthropicModelSettings
from pydantic_ai.models.google import GoogleModelSettings
from pydantic_ai.models.openai import (
    OpenAIChatModelSettings,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.settings import ModelSettings

from assistant_core.platform.types import ReasoningEffort

# A hung provider request must fail, and a reasoning model can need minutes.
_REQUEST_TIMEOUT_SECONDS = 900


def model_provider(model_id: str) -> str:
    """``"openai:gpt-5.6-luna"`` -> ``"openai"``."""
    provider, sep, _ = model_id.partition(":")
    if not sep or not provider:
        msg = f"Model id {model_id!r} is not in 'provider:model' form"
        raise ValueError(msg)
    return provider


def baked_model_id(agent: Any) -> str:
    """The stable ``provider:model`` id an agent was constructed with.

    Empty when the agent defers its model to the run.
    """
    model = agent.model
    if model is None:
        return ""
    if isinstance(model, str):
        return model
    raw: Any = model.model_id
    return str(raw)


def _provider_settings(provider: str) -> ModelSettings:
    """The provider-specific flags, before the shared timeout and effort."""
    if provider == "anthropic":
        # Anthropic prompt caching is opt-in.
        return AnthropicModelSettings(
            anthropic_cache_instructions=True,
            anthropic_cache_tool_definitions=True,
            anthropic_cache_messages=True,
        )
    if provider == "openai":
        # History processors rewrite the turn, so each request must be self
        # contained. The Responses API rejects item IDs it did not store.
        return OpenAIResponsesModelSettings(openai_send_reasoning_ids=False)
    if provider == "google":
        # Gemini caches implicitly and reads the cross-provider effort.
        return GoogleModelSettings()
    if provider == "ollama":
        # Ollama speaks the Chat Completions API, not the Responses API.
        return OpenAIChatModelSettings()
    if provider == "mock":
        return ModelSettings()
    msg = f"no model settings for provider {provider!r}"
    raise ValueError(msg)


def _effort_settings(provider: str, effort: ReasoningEffort | None) -> ModelSettings:
    """The effort as the provider takes it. Empty leaves the model's default."""
    if effort is None or effort == "none":
        return ModelSettings()
    if effort != "max":
        return ModelSettings(thinking=effort)
    if provider == "openai":
        # The Responses API names max, and its own effort wins over thinking.
        return OpenAIResponsesModelSettings(openai_reasoning_effort="max")
    return ModelSettings(thinking="xhigh")


def build_model_settings(
    model_id: str,
    *,
    thinking: ReasoningEffort | None = None,
) -> ModelSettings:
    """Provider-correct settings for ``model_id``.

    ``thinking`` from ``low`` to ``xhigh`` is the unified ``thinking`` setting.
    ``max`` has no unified level: an OpenAI model gets it as
    ``openai_reasoning_effort``, and every other provider gets ``xhigh``, the
    highest unified level. ``none`` and ``None`` omit it, so the model uses its
    own default.
    """
    provider = model_provider(model_id)
    settings = _provider_settings(provider)
    settings["timeout"] = _REQUEST_TIMEOUT_SECONDS
    settings.update(_effort_settings(provider, thinking))
    return settings
