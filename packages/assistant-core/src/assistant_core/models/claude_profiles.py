from pydantic_ai.profiles import ModelProfile, merge_profile
from pydantic_ai.profiles.anthropic import AnthropicModelProfile
from pydantic_ai.providers.anthropic import AnthropicProvider

_NO_FORCED_TOOL = AnthropicModelProfile(anthropic_supports_forced_tool_choice=False)

_ANSWERED: dict[str, AnthropicModelProfile] = {
    "claude-haiku-5-5": AnthropicModelProfile(
        supports_json_schema_output=True,
        anthropic_supports_adaptive_thinking=True,
        anthropic_supports_effort=True,
        anthropic_supports_xhigh_effort=True,
        anthropic_disallows_budget_thinking=True,
        anthropic_disallows_sampling_settings=True,
    ),
    "claude-sonnet-5-5": _NO_FORCED_TOOL,
    "claude-opus-5-5": _NO_FORCED_TOOL,
}


def claude_profile(model_name: str) -> ModelProfile | None:
    answered = next(
        (
            profile
            for prefix, profile in _ANSWERED.items()
            if model_name.startswith(prefix)
        ),
        None,
    )
    return merge_profile(AnthropicProvider.model_profile(model_name), answered)


class ClaudeProvider(AnthropicProvider):
    @staticmethod
    def model_profile(model_name: str) -> ModelProfile | None:
        return claude_profile(model_name)


__all__ = ["ClaudeProvider", "claude_profile"]
