from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.profiles.anthropic import AnthropicModelProfile
from pydantic_ai.providers.anthropic import AnthropicProvider

_HAIKU_5_5 = "claude-haiku-5-5"

_HAIKU_5_5_ANSWERED = AnthropicModelProfile(
    supports_json_schema_output=True,
    thinking_enabled_by_default=True,
    anthropic_supports_adaptive_thinking=True,
    anthropic_supports_effort=True,
    anthropic_supports_xhigh_effort=True,
    anthropic_disallows_budget_thinking=True,
    anthropic_disallows_sampling_settings=True,
)


class ClaudeProvider(AnthropicProvider):
    @staticmethod
    def model_profile(model_name: str) -> ModelProfile | None:
        packaged = AnthropicProvider.model_profile(model_name)
        if model_name.startswith(_HAIKU_5_5):
            return merge_profile(packaged, _HAIKU_5_5_ANSWERED)
        return packaged


__all__ = ["ClaudeProvider"]
