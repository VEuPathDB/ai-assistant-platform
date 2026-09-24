"""The trust boundary one turn's user text crosses before an agent reads it.

It reads the message's text only; an attached file is never screened here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NoReturn

from assistant_core.capabilities.injection_judge import ModelInjectionJudge
from assistant_core.capabilities.invisible_text import InvisibleTextScanner
from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)

INJECTION_SCANNER_NAME = "ModelInjectionJudge"
INVISIBLE_SCANNER_NAME = "InvisibleTextScanner"


class ScreeningRejectionError(RuntimeError):
    """A screening scanner refused the text. The host decides what it answers."""

    def __init__(self, scanner: str, risk_score: float) -> None:
        super().__init__(f"{scanner} rejected the input at risk score {risk_score}")
        self.scanner = scanner
        self.risk_score = risk_score


@dataclass
class UserInputScanner:
    """One scan per turn: the Unicode scan first, then the injection judge."""

    judge: ModelInjectionJudge
    invisible: InvisibleTextScanner = field(default_factory=InvisibleTextScanner)

    async def scan(self, text: str) -> None:
        """Scan one user message. Raise ``ScreeningRejectionError`` if refused."""
        _, is_visible, visible_score = self.invisible.scan(text)
        if not is_visible:
            self._refuse(INVISIBLE_SCANNER_NAME, visible_score)
        verdict = await self.judge.judge(text)
        if verdict.injection:
            self._refuse(INJECTION_SCANNER_NAME, verdict.confidence)

    def _refuse(self, scanner: str, risk_score: float) -> NoReturn:
        logger.warning(
            "Input rejected by security scanner",
            scanner=scanner,
            risk_score=risk_score,
        )
        raise ScreeningRejectionError(scanner, risk_score)
