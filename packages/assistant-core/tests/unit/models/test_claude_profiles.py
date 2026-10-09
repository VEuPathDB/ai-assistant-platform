import pytest
from pydantic_ai.models import infer_model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from assistant_core.models.claude_profiles import ClaudeProvider


def _model(model_name: str) -> AnthropicModel:
    model = infer_model(
        f"anthropic:{model_name}",
        provider_factory=lambda _: ClaudeProvider(api_key="sk-ant-test"),
    )
    assert isinstance(model, AnthropicModel)
    return model


def test_haiku_5_5_thinks_adaptively_at_an_effort_and_never_on_a_budget() -> None:
    profile = _model("claude-haiku-5-5").profile

    assert profile.get("anthropic_supports_adaptive_thinking") is True
    assert profile.get("anthropic_supports_effort") is True
    assert profile.get("anthropic_supports_xhigh_effort") is True
    assert profile.get("anthropic_disallows_budget_thinking") is True
    assert profile.get("anthropic_disallows_sampling_settings") is True
    assert profile.get("supports_json_schema_output") is True
    assert profile.get("thinking_enabled_by_default") is True


def test_haiku_5_5_can_still_be_forced_to_a_tool() -> None:
    profile = _model("claude-haiku-5-5").profile

    assert profile.get("supports_forced_tool_choice") is True
    assert profile.get("thinking_always_enabled") is False


@pytest.mark.parametrize(
    "model_name", ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5"]
)
def test_a_model_the_runtime_measured_nothing_for_keeps_the_packaged_profile(
    model_name: str,
) -> None:
    assert ClaudeProvider.model_profile(model_name) == AnthropicProvider.model_profile(
        model_name
    )


@pytest.mark.parametrize("model_name", ["claude-sonnet-5-5", "claude-opus-5-5"])
def test_the_packaged_5_5_sonnet_and_opus_are_never_forced_to_a_tool(
    model_name: str,
) -> None:
    profile = _model(model_name).profile

    assert profile.get("supports_forced_tool_choice") is False
    assert profile.get("anthropic_supports_adaptive_thinking") is True
