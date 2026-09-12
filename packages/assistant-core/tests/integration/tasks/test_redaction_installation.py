"""The job line a real worker emits carries no carried-state bytes.

Each ordering of a host's logging setup and its job registration runs in its
own process, so a logger an earlier ordering created cannot stand in for the
installation under test.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from tests.integration.tasks.redaction_probe import (
    MARKER,
    PROBE_COUNT,
    ProbeResult,
    Scenario,
    worker_name,
)

from assistant_core.tasks.redaction import REDACTION_MARKER

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
PROBE_MODULE = "tests.integration.tasks.redaction_probe"
PROBE_TIMEOUT_SECONDS = 240


async def _run_probe(scenario: Scenario, out_path: Path) -> tuple[str, ProbeResult]:
    """Run one probe process. Reports what it logged and what it measured."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PACKAGE_ROOT / "src"), str(PACKAGE_ROOT)],
    )
    env["LOG_FORMAT"] = "json"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        PROBE_MODULE,
        scenario.value,
        str(out_path),
        cwd=str(PACKAGE_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    logged = stdout.decode()
    assert process.returncode == 0, logged
    written = await asyncio.to_thread(out_path.read_text)
    return logged, ProbeResult.model_validate_json(written)


@pytest.mark.parametrize("scenario", list(Scenario))
async def test_a_real_worker_logs_the_job_without_the_carried_credential(
    scenario: Scenario,
    tmp_path: Path,
    patch_app_db_engine: None,
    db_cleaner: None,
) -> None:
    """The line is scrubbed, and the credential still reaches what runs here.

    It is restored twice: around the body, and around the turn that answers
    the call the body was deferred for.
    """
    del patch_app_db_engine, db_cleaner
    logged, result = await _run_probe(scenario, tmp_path / f"{scenario.value}.json")

    assert f"Starting job {result.job_name}" in logged
    assert REDACTION_MARKER in logged
    assert MARKER not in logged
    assert result.worker_logger == f"procrastinate.worker.{worker_name(scenario)}"
    assert result.reads == 2
    assert result.read_matches_marker
    assert result.task_status == "complete"
    assert result.counted == PROBE_COUNT
