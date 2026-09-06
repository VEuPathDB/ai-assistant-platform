"""A progress chunk's id names the task, and the lane inside it."""

from __future__ import annotations

from uuid import UUID

from assistant_core.graph.stream_events import task_progress_event

TASK = UUID("5a1f3c9e-0000-4000-8000-000000000001")


def test_a_task_that_runs_one_sequence_carries_the_bare_task_id() -> None:
    chunk = task_progress_event(task_id=TASK, percent=0.5, message="halfway")

    assert chunk.id == str(TASK)


def test_a_lane_suffixes_the_task_id() -> None:
    chunk = task_progress_event(
        task_id=TASK,
        percent=0.5,
        message="halfway",
        tool_specific={"variantId": "v3"},
        lane="v3",
    )

    assert chunk.id == f"{TASK}:v3"


def test_five_lanes_reconcile_into_five_parts() -> None:
    ids = {
        task_progress_event(
            task_id=TASK,
            percent=0.0,
            message="starting",
            tool_specific={"variantId": f"v{n}"},
            lane=f"v{n}",
        ).id
        for n in range(5)
    }

    assert len(ids) == 5


def test_the_lane_stays_in_the_payload_a_client_reads() -> None:
    chunk = task_progress_event(
        task_id=TASK,
        percent=0.25,
        message="scoring",
        tool_specific={"variantId": "v1"},
        lane="v1",
    )

    assert chunk.data["toolSpecific"] == {"variantId": "v1"}
