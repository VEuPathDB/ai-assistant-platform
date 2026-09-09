"""The trust boundary one turn's user text crosses before an agent reads it."""

from __future__ import annotations

import asyncio
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from assistant_core.capabilities.piguard import (
    InvisibleTextScanner,
    PIGuardScanner,
    TextScanner,
)
from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)

INJECTION_SCANNER_NAME = "PIGuardScanner"
INVISIBLE_SCANNER_NAME = "InvisibleTextScanner"

MAX_APPROVAL_LENGTH = 80

_PURE_APPROVAL_BYPASS = re.compile(
    r"""^\s*(?:
        yes|yep|yeah|ok|okay|sure|fine|
        approved?|proceed|go(?:\s+ahead)?|continue|
        run\s+it|execute(?:\s+(?:it|the\s+plan))?|launch(?:\s+it)?|
        do\s+it|confirm(?:ed)?|accept(?:ed)?|
        sounds?\s+good|looks?\s+good|
        perfect|great
    )[\s\.\!\,]*$""",
    re.IGNORECASE | re.VERBOSE,
)

_APPROVAL_CONNECTIVE_RE = re.compile(
    r"^\s*(?P<head>[^,.\!\?]{0,40}?)\s*[,\.]\s*(?P<tail>[^,.\!\?]{0,40})[\s\.\!\?]*$",
)


class ScreeningRejectionError(RuntimeError):
    """A screening scanner refused the text. The host decides what it answers."""

    def __init__(self, scanner: str, risk_score: float) -> None:
        super().__init__(f"{scanner} rejected the input at risk score {risk_score}")
        self.scanner = scanner
        self.risk_score = risk_score


def is_pure_approval(text: str) -> bool:
    """Strict whitelist: the text is nothing more than an approval phrase.

    One or two approval words joined by a connective, within
    ``MAX_APPROVAL_LENGTH`` characters. Everything else is not an approval.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > MAX_APPROVAL_LENGTH:
        return False
    if _PURE_APPROVAL_BYPASS.match(stripped):
        return True
    match = _APPROVAL_CONNECTIVE_RE.match(stripped)
    if match is None:
        return False
    head = match.group("head") or ""
    tail = match.group("tail") or ""
    return bool(
        _PURE_APPROVAL_BYPASS.match(head) and _PURE_APPROVAL_BYPASS.match(tail),
    )


@dataclass
class UserInputScanner:
    """Single-scan-per-turn trust boundary for user input.

    The scanners are built under a lock, so one caller pays the onnxruntime
    and tokenizer load. ``ensure_loaded`` moves that cost to startup. A caller
    that passes a scanner keeps it: nothing is built for that stage.
    """

    model_dir: Path
    injection_threshold: float = 0.90
    injection_scanner: TextScanner | None = None
    invisible_scanner: TextScanner | None = None
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def ensure_loaded(self) -> tuple[TextScanner, TextScanner]:
        if self.injection_scanner is not None and self.invisible_scanner is not None:
            return self.injection_scanner, self.invisible_scanner
        with self._lock:
            if self.injection_scanner is None:
                self.injection_scanner = PIGuardScanner(
                    model_dir=self.model_dir,
                    threshold=self.injection_threshold,
                )
            if self.invisible_scanner is None:
                self.invisible_scanner = InvisibleTextScanner()
            return self.injection_scanner, self.invisible_scanner

    def scan(self, text: str) -> None:
        """Scan one user message. Raise ``ScreeningRejectionError`` if refused.

        Text that matches the pure-approval whitelist skips the injection
        model: short affirmatives score above the injection threshold although
        they carry no instruction.
        """
        if is_pure_approval(text):
            return
        injection, invisible = self.ensure_loaded()
        _, valid, score = injection.scan(text)
        if not valid:
            logger.warning(
                "Input rejected by security scanner",
                scanner=INJECTION_SCANNER_NAME,
                risk_score=score,
            )
            raise ScreeningRejectionError(INJECTION_SCANNER_NAME, score)
        _, visible_valid, visible_score = invisible.scan(text)
        if not visible_valid:
            logger.warning(
                "Input rejected by security scanner",
                scanner=INVISIBLE_SCANNER_NAME,
                risk_score=visible_score,
            )
            raise ScreeningRejectionError(INVISIBLE_SCANNER_NAME, visible_score)

    async def scan_async(self, text: str) -> None:
        """Offload the CPU-bound scan to a thread so the event loop stays free."""
        await asyncio.to_thread(self.scan, text)
