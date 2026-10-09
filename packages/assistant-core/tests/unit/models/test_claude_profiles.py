import pytest
from pydantic_ai.models import infer_model
from pydantic_ai.models.anthropic import AnthropicModel

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


@pytest.mark.parametrize("model_name", ["claude-sonnet-5-5", "claude-opus-5-5"])
def test_the_5_5_sonnet_and_opus_are_never_forced_to_a_tool(model_name: str) -> None:
    profile = _model(model_name).profile

    assert profile.get("anthropic_supports_forced_tool_choice") is False
    assert profile.get("anthropic_supports_adaptive_thinking") is True


def test_a_model_the_runtime_measured_nothing_for_keeps_the_packaged_profile() -> None:
    profile = _model("claude-haiku-4-5").profile

    assert profile.get("anthropic_supports_adaptive_thinking") is False
    assert profile.get("anthropic_supports_forced_tool_choice") is True
