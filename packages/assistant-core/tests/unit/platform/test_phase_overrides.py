"""The per-role picks a request carries, as the task row stores them."""

from assistant_core.platform.context import PhaseOverrides


def test_the_top_efforts_survive_the_task_row() -> None:
    """A completion turn reads back every effort the deferring turn ran with."""
    picks = {"lead": "max", "build": "xhigh", "verify": "low"}
    stored = PhaseOverrides.model_validate({"reasoning": picks}).model_dump(mode="json")

    assert PhaseOverrides.model_validate(stored).reasoning == picks
