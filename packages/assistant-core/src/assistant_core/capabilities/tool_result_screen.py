"""The scan a tool source's result crosses before the model reads it."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from hashlib import sha256

from assistant_core.capabilities.injection_judge import (
    MAX_JUDGED_CHARS,
    InjectionVerdict,
    ModelInjectionJudge,
)
from assistant_core.mcp.untrusted import OutputScan, ScanVerdict
from assistant_core.platform.logging import get_logger

logger = get_logger(__name__)

WITHHELD = (
    "A result from this tool carried instructions addressed to the assistant, "
    "so it was not passed on."
)

UNJUDGED = (
    "A result from this tool was too long to screen for instructions addressed "
    "to the assistant, so it was not passed on."
)

# The windows of one result, judged together. A result that needs more is
# withheld unjudged, because an unread trust boundary fails closed.
MAX_JUDGED_WINDOWS = 8

MAX_CACHED_VERDICTS = 1024


@dataclass
class VerdictCache:
    """A bounded LRU of verdicts, keyed by the digest of the judged text."""

    limit: int = MAX_CACHED_VERDICTS
    _entries: OrderedDict[str, InjectionVerdict] = field(
        default_factory=OrderedDict,
        init=False,
        repr=False,
    )

    def read(self, digest: str) -> InjectionVerdict | None:
        verdict = self._entries.get(digest)
        if verdict is not None:
            self._entries.move_to_end(digest)
        return verdict

    def write(self, digest: str, verdict: InjectionVerdict) -> None:
        self._entries[digest] = verdict
        self._entries.move_to_end(digest)
        while len(self._entries) > self.limit:
            self._entries.popitem(last=False)


async def judge_windows(judge: ModelInjectionJudge, text: str) -> InjectionVerdict:
    """Judge every window of one text at once.

    An injected window makes the text an injection, at the highest confidence
    any injected window carried. A text no window injects keeps the confidence
    of its least sure window.
    """
    windows = [
        text[start : start + MAX_JUDGED_CHARS]
        for start in range(0, len(text), MAX_JUDGED_CHARS)
    ] or [text]
    verdicts = await asyncio.gather(*(judge.judge(window) for window in windows))
    injected = [v.confidence for v in verdicts if v.injection]
    if injected:
        return InjectionVerdict(injection=True, confidence=max(injected))
    return InjectionVerdict(
        injection=False,
        confidence=min(v.confidence for v in verdicts),
    )


def screened_output(judge: ModelInjectionJudge) -> OutputScan:
    """The scan a deployment installs on the results of its tool sources."""
    cache = VerdictCache()
    ceiling = MAX_JUDGED_CHARS * MAX_JUDGED_WINDOWS

    async def scan(text: str) -> ScanVerdict:
        if len(text) > ceiling:
            logger.warning(
                "Tool result withheld unjudged: it is longer than the screen reads",
                text_length=len(text),
                ceiling=ceiling,
            )
            return ScanVerdict(text=UNJUDGED)
        digest = sha256(text.encode()).hexdigest()
        verdict = cache.read(digest)
        if verdict is None:
            verdict = await judge_windows(judge, text)
            cache.write(digest, verdict)
        if not verdict.injection:
            return ScanVerdict(text=text)
        logger.warning(
            "Tool result withheld by the injection judge",
            confidence=verdict.confidence,
            text_length=len(text),
        )
        return ScanVerdict(text=WITHHELD)

    return scan
