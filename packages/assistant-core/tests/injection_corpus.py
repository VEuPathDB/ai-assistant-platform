"""The labelled screening corpus this package ships, and its shape."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

CORPUS = Path(__file__).resolve().parent / "fixtures" / "injection_corpus.jsonl"

CORPUS_LINES = 88
BENIGN_LINES = 73
INJECTION_LINES = 15


class CorpusLine(BaseModel):
    """One labelled message of the corpus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    label: str

    @property
    def is_injection(self) -> bool:
        return self.label == "injection"


def read_corpus() -> list[CorpusLine]:
    return [
        CorpusLine.model_validate(json.loads(line))
        for line in CORPUS.read_text().splitlines()
        if line.strip()
    ]
