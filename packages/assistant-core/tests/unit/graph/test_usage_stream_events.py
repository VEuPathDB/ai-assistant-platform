from assistant_core.graph.stream_events import (
    SubAgentCallPayload,
    lead_usage_event,
    sub_agent_call_event,
    turn_usage_event,
)


def test_turn_usage_event_is_transient() -> None:
    chunk = turn_usage_event(total_tokens=1234, cost_usd="0.05")
    assert chunk.type == "data-turn-usage"
    assert chunk.transient is True
    assert chunk.data == {"totalTokens": 1234, "costUsd": "0.05"}


def test_lead_usage_event_has_stable_id_and_payload() -> None:
    chunk = lead_usage_event(model_id="openai:gpt-4.1", tokens=999, cost_usd="0.012")
    assert chunk.type == "data-lead-usage"
    # Stable id so repeated live emissions reconcile into one persisted part.
    assert chunk.id == "lead-usage"
    assert chunk.data == {
        "modelId": "openai:gpt-4.1",
        "tokens": 999,
        "costUsd": "0.012",
        "contextTokens": 0,
        "contextWindow": 0,
    }


def test_lead_usage_event_carries_the_context_fill() -> None:
    chunk = lead_usage_event(
        model_id="openai:gpt-4.1",
        tokens=999,
        cost_usd="0.012",
        context_tokens=310_000,
        context_window=1_050_000,
    )
    assert chunk.data["contextTokens"] == 310_000
    assert chunk.data["contextWindow"] == 1_050_000


def test_sub_agent_context_fill_defaults_to_unknown() -> None:
    payload = SubAgentCallPayload(
        tool_call_id="call_3",
        sub_agent="run_frame",
        phase="frame",
        state="completed",
    )
    assert payload.context_tokens == 0
    assert payload.context_window == 0


def test_sub_agent_completed_carries_tokens_and_cost() -> None:
    chunk = sub_agent_call_event(
        SubAgentCallPayload(
            tool_call_id="call_1",
            sub_agent="run_discovery",
            phase="discovery",
            state="completed",
            tokens=18742,
            cost_usd="0.006",
        )
    )
    assert chunk.id == "call_1"
    assert chunk.data["tokens"] == 18742
    assert chunk.data["costUsd"] == "0.006"


def test_sub_agent_usage_defaults_to_zero() -> None:
    payload = SubAgentCallPayload(
        tool_call_id="call_2",
        sub_agent="run_scoping",
        phase="scoping",
        state="started",
    )
    assert payload.tokens == 0
    assert payload.cost_usd == "0"
