"""The provider-correct model settings the runtime builds."""

from typing import get_args

import pytest
from pydantic_ai import Agent
from pydantic_ai.models import infer_model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.models.test import TestModel

from assistant_core.models.settings import (
    baked_model_id,
    build_model_settings,
    model_provider,
)
from assistant_core.platform.types import ModelProvider


class TestModelProvider:
    def test_openai(self) -> None:
        assert model_provider("openai:gpt-4.1-mini") == "openai"

    def test_anthropic(self) -> None:
        assert model_provider("anthropic:claude-opus-4-6") == "anthropic"

    def test_google(self) -> None:
        assert model_provider("google:gemini-2.5-pro") == "google"

    def test_an_id_without_a_provider_is_refused(self) -> None:
        with pytest.raises(ValueError, match="provider:model"):
            model_provider("gpt-4.1-mini")


class TestBakedModelId:
    def test_an_agent_that_defers_its_check_reports_the_id_it_was_given(
        self,
    ) -> None:
        agent = Agent("openai:gpt-4.1-mini", defer_model_check=True)

        assert baked_model_id(agent) == "openai:gpt-4.1-mini"

    def test_an_agent_with_no_model_reports_nothing(self) -> None:
        assert baked_model_id(Agent()) == ""

    def test_an_agent_built_on_a_model_object_reports_that_model_id(self) -> None:
        assert baked_model_id(Agent(TestModel())) == "test:test"


class TestOpenAIIdsResolveToTheResponsesApi:
    """A bare ``openai:`` prefix means the Responses API.

    The runtime hands pydantic-ai its stable ids unchanged, so this is the
    assumption that makes the openai branch of the settings table correct.
    """

    def test_bare_openai_prefix_is_the_responses_api(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        assert isinstance(infer_model("openai:gpt-5-mini"), OpenAIResponsesModel)

    def test_it_holds_across_the_openai_families(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        for model in ("gpt-4.1", "gpt-5", "gpt-5.4", "o3", "o4-mini"):
            assert isinstance(infer_model(f"openai:{model}"), OpenAIResponsesModel)


class TestBuildModelSettings:
    def test_anthropic_enables_caching(self) -> None:
        data = dict(build_model_settings("anthropic:claude-opus-4-6"))
        assert data["anthropic_cache_instructions"] is True
        assert data["anthropic_cache_tool_definitions"] is True
        assert data["anthropic_cache_messages"] is True

    def test_anthropic_caching_composes_with_thinking(self) -> None:
        data = dict(build_model_settings("anthropic:claude-opus-4-6", thinking="high"))
        assert data["anthropic_cache_instructions"] is True
        assert data["thinking"] == "high"

    def test_openai_thinking_applied(self) -> None:
        data = dict(build_model_settings("openai:gpt-5.4", thinking="high"))
        assert data["thinking"] == "high"

    def test_openai_caching_is_automatic_no_flags(self) -> None:
        data = dict(build_model_settings("openai:gpt-4.1-mini"))
        assert "anthropic_cache_instructions" not in data

    def test_google_thinking_applied(self) -> None:
        data = dict(build_model_settings("google:gemini-2.5-pro", thinking="medium"))
        assert data["thinking"] == "medium"

    def test_thinking_none_omitted(self) -> None:
        data = dict(build_model_settings("openai:gpt-4.1-mini", thinking="none"))
        assert "thinking" not in data

    def test_thinking_default_omitted(self) -> None:
        data = dict(build_model_settings("openai:gpt-4.1-mini"))
        assert "thinking" not in data


class TestEveryRequestCarriesATimeout:
    """A provider request that never returns must fail instead of hanging."""

    def test_openai_carries_the_timeout(self) -> None:
        assert build_model_settings("openai:gpt-5.6-luna")["timeout"] == 900

    def test_anthropic_carries_the_timeout(self) -> None:
        assert build_model_settings("anthropic:claude-opus-4-6")["timeout"] == 900

    def test_google_carries_the_timeout(self) -> None:
        assert build_model_settings("google:gemini-2.5-pro")["timeout"] == 900

    def test_timeout_survives_every_thinking_effort(self) -> None:
        for effort in ("none", "low", "medium", "high"):
            for model in ("openai:gpt-5.6-luna", "anthropic:claude-opus-4-6"):
                settings = build_model_settings(model, thinking=effort)

                assert settings["timeout"] == 900, (model, effort)

    def test_timeout_does_not_disturb_provider_settings(self) -> None:
        anthropic = build_model_settings("anthropic:claude-opus-4-6", thinking="high")
        openai = build_model_settings("openai:gpt-5.6-luna", thinking="high")

        assert anthropic.get("anthropic_cache_instructions") is True
        assert anthropic["thinking"] == "high"
        assert openai.get("openai_send_reasoning_ids") is False
        assert openai["thinking"] == "high"


class TestOpenAiItemIdsAreNotSentBack:
    """The Responses API validates the item ids a request echoes back.

    Every agent runs the history processors, so the history it sends never
    matches what the API returned and the ids must stay out of it.
    """

    def test_openai_does_not_send_item_ids(self) -> None:
        settings = build_model_settings("openai:gpt-5.6-luna")

        assert settings.get("openai_send_reasoning_ids") is False

    def test_it_is_disabled_regardless_of_thinking_effort(self) -> None:
        for effort in ("none", "low", "medium", "high"):
            settings = build_model_settings("openai:gpt-5.6-luna", thinking=effort)

            assert settings.get("openai_send_reasoning_ids") is False, effort

    def test_anthropic_is_untouched(self) -> None:
        settings = build_model_settings("anthropic:claude-sonnet-5")

        assert "openai_send_reasoning_ids" not in settings
        assert settings.get("anthropic_cache_messages") is True

    def test_thinking_still_applied_for_openai(self) -> None:
        settings = build_model_settings("openai:gpt-5.6-luna", thinking="high")

        assert settings.get("thinking") == "high"
        assert settings.get("openai_send_reasoning_ids") is False


class TestEveryProviderHasItsOwnSettings:
    """A provider that falls through to another provider's settings carries
    flags its API never reads."""

    def test_google_carries_no_openai_flag(self) -> None:
        settings = build_model_settings("google:gemini-3.1-pro-preview")

        assert "openai_send_reasoning_ids" not in settings
        assert "anthropic_cache_messages" not in settings

    def test_google_still_carries_the_reasoning_effort(self) -> None:
        settings = build_model_settings(
            "google:gemini-3.1-pro-preview", thinking="high"
        )

        assert settings["thinking"] == "high"

    def test_ollama_carries_no_responses_api_flag(self) -> None:
        """Ollama speaks Chat Completions, where the flag does not exist."""
        settings = build_model_settings("ollama:qwen3")

        assert "openai_send_reasoning_ids" not in settings
        assert settings["timeout"] == 900

    def test_mock_carries_no_provider_flag(self) -> None:
        settings = build_model_settings("mock:deterministic")

        assert "openai_send_reasoning_ids" not in settings
        assert "anthropic_cache_messages" not in settings

    def test_an_unknown_provider_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no model settings"):
            build_model_settings("bedrock:nova-pro")

    def test_the_provider_set_is_the_declared_one(self) -> None:
        """The settings table covers exactly the providers the type declares."""
        declared = sorted(get_args(ModelProvider.__value__))
        resolved = sorted(
            provider
            for provider in declared
            if build_model_settings(f"{provider}:x")["timeout"] == 900
        )

        assert resolved == declared
