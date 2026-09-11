from assistant_core.graph.stream_events import turn_usage_event


def test_turn_usage_event_is_transient() -> None:
    chunk = turn_usage_event(total_tokens=1234, cost_usd="0.05")
    assert chunk.type == "data-turn-usage"
    assert chunk.transient is True
    assert chunk.data == {"totalTokens": 1234, "costUsd": "0.05"}
