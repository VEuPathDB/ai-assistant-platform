"""The corpus the acceptance run scores against keeps its population."""

from __future__ import annotations

from tests.injection_corpus import (
    BENIGN_LINES,
    CORPUS_LINES,
    INJECTION_LINES,
    read_corpus,
)


def test_the_corpus_holds_the_population_the_acceptance_run_scores() -> None:
    lines = read_corpus()
    injections = [line for line in lines if line.is_injection]

    assert len(lines) == CORPUS_LINES
    assert len(injections) == INJECTION_LINES
    assert len(lines) - len(injections) == BENIGN_LINES


def test_every_line_carries_one_of_the_two_labels_and_a_message() -> None:
    lines = read_corpus()

    assert {line.label for line in lines} == {"benign", "injection"}
    assert all(line.text.strip() for line in lines)
