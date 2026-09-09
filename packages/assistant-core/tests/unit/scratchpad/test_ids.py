"""The note id shape and the token approximation the budget gate reads."""

from __future__ import annotations

import re

from assistant_core.scratchpad.ids import approx_body_tokens, mint_note_id


def test_a_minted_id_is_the_prefix_and_six_hex_digits() -> None:
    assert re.fullmatch(r"n-[0-9a-f]{6}", mint_note_id())


def test_a_thousand_ids_collide_almost_never() -> None:
    assert len({mint_note_id() for _ in range(1000)}) > 950


def test_an_empty_body_approximates_to_no_tokens() -> None:
    assert approx_body_tokens("") == 0


def test_eleven_characters_approximate_to_two_tokens() -> None:
    assert approx_body_tokens("hello world") == 2


def test_four_hundred_characters_approximate_to_a_hundred_tokens() -> None:
    assert approx_body_tokens("x" * 400) == 100
