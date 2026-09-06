"""The admission record: what answered, what it declared, what each family settled."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from mcp_conformance import __version__
from mcp_conformance._evidence import ServerRecord, ShapeEvidence, ToolRecord
from mcp_conformance._wire import WireModel

SUITE_NAME = "veupathdb-mcp-conformance"

Outcome = Literal["passed", "failed", "skipped", "error"]
Verdict = Literal["pass", "fail", "incomplete"]

REDACTED = "<redacted>"

# The one thing the report leaves out of a tool row. An operator signs what a
# tool returns; what it takes is the server's own document.
_TOOL_DETAIL = {"tools": {"__all__": {"input_schema"}}}


class FamilySpec(WireModel):
    """One family, in the numbering the design document uses."""

    id: str
    number: int
    title: str
    module: str


FAMILIES: tuple[FamilySpec, ...] = (
    FamilySpec(id="shape", number=1, title="Shape", module="test_shape"),
    FamilySpec(id="auth", number=2, title="Auth", module="test_auth"),
    FamilySpec(
        id="annotations",
        number=3,
        title="Annotations",
        module="test_annotations",
    ),
    FamilySpec(id="errors", number=4, title="Errors", module="test_errors"),
    FamilySpec(
        id="timeouts",
        number=5,
        title="Timeouts and cancellation",
        module="test_timeouts",
    ),
    FamilySpec(id="stability", number=6, title="Stability", module="test_stability"),
)

_BY_MODULE = {spec.module: spec for spec in FAMILIES}


def family_of(module: str) -> FamilySpec | None:
    """The family a module is, by the name it ships under."""
    return _BY_MODULE.get(module)


def check_id(module: str, nodeid: str) -> str:
    """One check, named the same way however the runner invoked pytest.

    A node id carries a path relative to the runner's own root directory, and
    that path is empty when the two have no common root.
    """
    return f"{module}.py::{nodeid.rsplit('::', maxsplit=1)[-1]}"


def redact(text: str, credentials: tuple[str, ...]) -> str:
    for credential in credentials:
        text = text.replace(credential, REDACTED)
    return text


class SuiteInfo(WireModel):
    name: str = SUITE_NAME
    version: str = __version__


class ReportTarget(WireModel):
    endpoint: str
    credential: Literal["none", "one", "two"]


class CheckResult(WireModel):
    id: str
    outcome: Outcome
    message: str | None = None


class FamilyResult(WireModel):
    id: str
    number: int
    title: str
    passed: int
    failed: int
    skipped: int
    checks: list[CheckResult]


class AdmissionReport(WireModel):
    suite: SuiteInfo = SuiteInfo()
    generated_at: str
    verdict: Verdict
    target: ReportTarget | None = None
    server: ServerRecord | None = None
    tools: list[ToolRecord] = Field(default_factory=list)
    families: list[FamilyResult] = Field(default_factory=list)

    def rendered(self, credentials: tuple[str, ...]) -> str:
        """The report as JSON, with every credential taken out of it."""
        body = self.model_dump_json(by_alias=True, indent=2, exclude=_TOOL_DETAIL)
        return redact(body, credentials) + "\n"


def verdict_of(families: list[FamilyResult]) -> Verdict:
    """A skipped check is not a passed one, and a partial run is not a pass."""
    if any(family.failed for family in families):
        return "fail"
    if any(family.skipped or not family.checks for family in families):
        return "incomplete"
    return "pass"


class ReportAccumulator:
    """Collects what the run saw, and answers with the report at the end."""

    def __init__(
        self,
        target: ReportTarget | None = None,
        credentials: tuple[str, ...] = (),
    ) -> None:
        self._target = target
        self._credentials = credentials
        self._checks: dict[str, CheckResult] = {}
        self._modules: dict[str, str] = {}
        self._shape: ShapeEvidence | None = None

    @property
    def credentials(self) -> tuple[str, ...]:
        return self._credentials

    def record_shape(self, evidence: ShapeEvidence) -> None:
        self._shape = evidence

    def assign(self, nodeid: str, module: str) -> None:
        """What a collected test's file is called, which its node id may not say."""
        self._modules[nodeid] = module

    def record_check(self, nodeid: str, outcome: Outcome, message: str) -> None:
        module = self._modules.get(nodeid, "")
        if family_of(module) is None:
            return
        identifier = check_id(module, nodeid)
        known = self._checks.get(identifier)
        if known is not None and known.outcome in ("failed", "error"):
            return
        trimmed = redact(" ".join(message.split()), self._credentials)[:2000]
        self._checks[identifier] = CheckResult(
            id=identifier,
            outcome=outcome,
            message=trimmed or None,
        )

    def _family_results(self) -> list[FamilyResult]:
        results: list[FamilyResult] = []
        for spec in FAMILIES:
            checks = [
                check
                for check in self._checks.values()
                if check.id.startswith(f"{spec.module}.py::")
            ]
            outcomes = [check.outcome for check in checks]
            results.append(
                FamilyResult(
                    id=spec.id,
                    number=spec.number,
                    title=spec.title,
                    passed=outcomes.count("passed"),
                    failed=outcomes.count("failed") + outcomes.count("error"),
                    skipped=outcomes.count("skipped"),
                    checks=checks,
                )
            )
        return results

    def build(self) -> AdmissionReport:
        families = self._family_results()
        return AdmissionReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            verdict=verdict_of(families),
            target=self._target,
            server=None if self._shape is None else self._shape.server,
            tools=[] if self._shape is None else list(self._shape.tools),
            families=families,
        )
