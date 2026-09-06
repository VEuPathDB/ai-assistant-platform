"""The pytest plugin: what a runner names, what the families read, where the report lands."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_conformance import hooks
from mcp_conformance._evidence import (
    AnnotationEvidence,
    AuthEvidence,
    ErrorEvidence,
    ShapeEvidence,
    StabilityEvidence,
    TimeoutEvidence,
)
from mcp_conformance._options import (
    BEARER_ENV,
    BEARER_OPTION,
    DEFAULT_MAX_CALL_SECONDS,
    ENDPOINT_ENV,
    ENDPOINT_OPTION,
    ISOLATION_TOOL_OPTION,
    MAX_CALL_SECONDS_OPTION,
    REPORT_OPTION,
    SAMPLE_ARGS_OPTION,
    SECOND_BEARER_ENV,
    SECOND_BEARER_OPTION,
    SLOW_TOOL_OPTION,
    ConformanceTarget,
    from_environment,
    sample_arguments,
)
from mcp_conformance._probe import (
    AccountSnapshot,
    probe_annotations,
    probe_auth,
    probe_errors,
    probe_shape,
    probe_stability,
    probe_timeouts,
)
from mcp_conformance._report import Outcome, ReportAccumulator, ReportTarget

_NO_ENDPOINT = f"{ENDPOINT_OPTION} names no server, so the families have nothing to read"


def pytest_addhooks(pluginmanager: pytest.PytestPluginManager) -> None:
    pluginmanager.add_hookspecs(hooks)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("mcp-conformance", "MCP tool-server conformance")
    group.addoption(
        ENDPOINT_OPTION,
        default=None,
        help=f"Streamable-HTTP MCP endpoint under test. Also read from ${ENDPOINT_ENV}.",
    )
    group.addoption(
        BEARER_OPTION,
        default=None,
        help=f"Credential the calls carry. Also read from ${BEARER_ENV}.",
    )
    group.addoption(
        SECOND_BEARER_OPTION,
        default=None,
        help=(
            "A second identity, which turns on the isolation check. "
            f"Also read from ${SECOND_BEARER_ENV}."
        ),
    )
    group.addoption(
        REPORT_OPTION,
        default=None,
        help="Where the admission report JSON is written.",
    )
    group.addoption(
        SAMPLE_ARGS_OPTION,
        default=None,
        help="JSON object, or a path to one, of arguments a call may use per tool.",
    )
    group.addoption(
        SLOW_TOOL_OPTION,
        default=None,
        help="The tool the timeout family drives past its budget.",
    )
    group.addoption(
        ISOLATION_TOOL_OPTION,
        default=None,
        help="The tool that names a resource the second identity owns.",
    )
    group.addoption(
        MAX_CALL_SECONDS_OPTION,
        default=None,
        help=f"Budget for a tool that declares none. Default {DEFAULT_MAX_CALL_SECONDS}.",
    )


def option_value(config: pytest.Config, name: str, env: str) -> str | None:
    """The option a runner set, or the environment variable that stands in."""
    raw = config.getoption(name, default=None)
    value = str(raw).strip() if raw else ""
    return value or from_environment(env)


def target_of(config: pytest.Config) -> ConformanceTarget | None:
    endpoint = option_value(config, ENDPOINT_OPTION, ENDPOINT_ENV)
    if endpoint is None:
        return None
    samples = option_value(config, SAMPLE_ARGS_OPTION, "")
    budget = option_value(config, MAX_CALL_SECONDS_OPTION, "")
    return ConformanceTarget(
        endpoint=endpoint,
        bearer=option_value(config, BEARER_OPTION, BEARER_ENV),
        second_bearer=option_value(config, SECOND_BEARER_OPTION, SECOND_BEARER_ENV),
        sample_arguments={} if samples is None else sample_arguments(samples),
        slow_tool=option_value(config, SLOW_TOOL_OPTION, ""),
        isolation_tool=option_value(config, ISOLATION_TOOL_OPTION, ""),
        max_call_seconds=DEFAULT_MAX_CALL_SECONDS if budget is None else float(budget),
    )


def _outcome_of(report: pytest.TestReport) -> Outcome | None:
    """What one phase of one test says about its check."""
    if report.when == "call":
        if report.failed:
            return "failed"
        return "skipped" if report.skipped else "passed"
    if report.passed:
        return None
    return "skipped" if report.skipped else "error"


class ConformanceReportPlugin:
    """Turns the run's outcomes into the record an operator signs."""

    def __init__(self, config: pytest.Config) -> None:
        target = target_of(config)
        report_path = option_value(config, REPORT_OPTION, "")
        self.path = None if report_path is None else Path(report_path)
        self.accumulator = ReportAccumulator(
            target=_report_target(target),
            credentials=() if target is None else target.credentials,
        )

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            self.accumulator.assign(item.nodeid, item.path.stem)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        outcome = _outcome_of(report)
        if outcome is not None:
            self.accumulator.record_check(report.nodeid, outcome, report.longreprtext)

    def pytest_sessionfinish(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rendered = self.accumulator.build().rendered(self.accumulator.credentials)
        self.path.write_text(rendered)


def _report_target(target: ConformanceTarget | None) -> ReportTarget | None:
    if target is None:
        return None
    held = len([value for value in (target.bearer, target.second_bearer) if value])
    return ReportTarget(
        endpoint=target.endpoint,
        credential=("none", "one", "two")[held],
    )


REPORT_KEY = pytest.StashKey[ConformanceReportPlugin]()


def pytest_configure(config: pytest.Config) -> None:
    plugin = ConformanceReportPlugin(config)
    config.stash[REPORT_KEY] = plugin
    config.pluginmanager.register(plugin, "mcp-conformance-report")


def pytest_report_header(config: pytest.Config) -> str | None:
    target = target_of(config)
    if target is None:
        return None
    return f"mcp-conformance: {target.endpoint}"


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    config: pytest.Config,
) -> None:
    plugin = config.stash[REPORT_KEY]
    if plugin.path is None:
        return
    verdict = plugin.accumulator.build().verdict
    terminalreporter.write_line(f"mcp-conformance verdict: {verdict} ({plugin.path})")


@pytest.fixture(scope="session")
def mcp_target(request: pytest.FixtureRequest) -> ConformanceTarget:
    """The server under test. Without one, every family skips."""
    target = target_of(request.config)
    if target is None:
        pytest.skip(_NO_ENDPOINT)
    return target


@pytest.fixture(scope="session")
def mcp_shape_evidence(
    request: pytest.FixtureRequest,
    mcp_target: ConformanceTarget,
) -> ShapeEvidence:
    evidence = asyncio.run(probe_shape(mcp_target))
    request.config.stash[REPORT_KEY].accumulator.record_shape(evidence)
    return evidence


@pytest.fixture(scope="session")
def mcp_error_evidence(
    mcp_target: ConformanceTarget,
    mcp_shape_evidence: ShapeEvidence,
) -> ErrorEvidence:
    return asyncio.run(probe_errors(mcp_target, list(mcp_shape_evidence.tools)))


@pytest.fixture(scope="session")
def mcp_stability_evidence(mcp_target: ConformanceTarget) -> StabilityEvidence:
    return asyncio.run(probe_stability(mcp_target))


@pytest.fixture(scope="session")
def mcp_account_state(request: pytest.FixtureRequest) -> AccountSnapshot | None:
    """What this account holds, for the checks that compare it before and after.

    The operator's harness answers the hook. Without it, family 3 reports what
    it could not settle.
    """
    supplied: AccountSnapshot | None = request.config.hook.pytest_mcp_account_state()
    return supplied


@pytest.fixture(scope="session")
def mcp_auth_evidence(
    mcp_target: ConformanceTarget,
    mcp_shape_evidence: ShapeEvidence,
) -> AuthEvidence:
    return asyncio.run(probe_auth(mcp_target, list(mcp_shape_evidence.tools)))


@pytest.fixture(scope="session")
def mcp_annotation_evidence(
    mcp_target: ConformanceTarget,
    mcp_shape_evidence: ShapeEvidence,
    mcp_account_state: AccountSnapshot | None,
) -> AnnotationEvidence:
    return asyncio.run(
        probe_annotations(
            mcp_target,
            list(mcp_shape_evidence.tools),
            mcp_account_state,
        )
    )


@pytest.fixture(scope="session")
def mcp_timeout_evidence(
    mcp_target: ConformanceTarget,
    mcp_shape_evidence: ShapeEvidence,
) -> TimeoutEvidence:
    return asyncio.run(
        probe_timeouts(
            mcp_target,
            list(mcp_shape_evidence.tools),
            mcp_shape_evidence.initialize_seconds,
        )
    )
