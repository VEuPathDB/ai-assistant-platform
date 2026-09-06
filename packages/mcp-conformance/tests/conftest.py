"""How the suite's own tests start a fixture server and run a family at it."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fixture_server import BEARER_A, Defect, FixtureServer, free_port

ServerFactory = Callable[[Defect], FixtureServer]
FamilyRunner = Callable[..., pytest.RunResult]


@pytest.fixture(scope="session")
def servers() -> Iterator[ServerFactory]:
    """One server per defect the run asks for, all stopped at the end."""
    started: dict[Defect, FixtureServer] = {}

    def start(defect: Defect) -> FixtureServer:
        if defect not in started:
            server = FixtureServer(defect, free_port())
            server.start()
            started[defect] = server
        return started[defect]

    yield start
    for server in started.values():
        server.stop()


@pytest.fixture
def run_family(pytester: pytest.Pytester) -> FamilyRunner:
    """Run one shipped family against a fixture server, as a runner would."""

    def run(module: str, server: FixtureServer, *extra: str) -> pytest.RunResult:
        target = f"mcp_conformance.{module}" if module else "mcp_conformance"
        return pytester.runpytest_subprocess(
            "--pyargs",
            target,
            "--mcp-endpoint",
            server.url,
            "--mcp-bearer",
            BEARER_A,
            "-p",
            "no:cacheprovider",
            "-rf",
            *extra,
        )

    return run


def assert_clean_pass(result: pytest.RunResult, checks: int) -> None:
    """A family is green only when every one of its checks ran and passed."""
    result.assert_outcomes(passed=checks)
    assert result.ret == 0


_ACCOUNT_HOOK = '''
import httpx

ACCOUNT_URL = "{url}"
BEARER = "{bearer}"


def pytest_mcp_account_state():
    async def snapshot():
        async with httpx.AsyncClient() as client:
            answer = await client.get(
                ACCOUNT_URL,
                headers={{"Authorization": "Bearer " + BEARER}},
            )
        return list(answer.json()["notes"])

    return snapshot
'''


def account_hook(pytester: pytest.Pytester, server: FixtureServer) -> None:
    """Write the extension point a runner supplies, as the README documents it."""
    pytester.makepyfile(
        account_hook=_ACCOUNT_HOOK.format(url=server.account_url, bearer=BEARER_A)
    )


def failed_checks(result: pytest.RunResult) -> set[str]:
    """The checks a run reported as failures, by name."""
    return {
        line.split("::", 1)[1].split(" ", 1)[0]
        for line in result.outlines
        if line.startswith("FAILED ") and "::" in line
    }
