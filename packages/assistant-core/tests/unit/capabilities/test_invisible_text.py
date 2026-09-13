"""The Unicode half of the trust boundary: what counts as invisible."""

from __future__ import annotations

from assistant_core.capabilities.invisible_text import InvisibleTextScanner


class TestInvisibleTextScanner:
    def test_pure_ascii_passes(self) -> None:
        text, is_valid, score = InvisibleTextScanner().scan("hello world")
        assert is_valid
        assert text == "hello world"
        assert score == 0.0

    def test_normal_unicode_passes(self) -> None:
        _text, is_valid, score = InvisibleTextScanner().scan(
            "a resume with naive accents: résumé naïve",
        )
        assert is_valid
        assert score == 0.0

    def test_invisible_format_char_rejected(self) -> None:
        text, is_valid, score = InvisibleTextScanner().scan("hello\u200bworld")
        assert not is_valid
        assert text == "helloworld"
        assert score == 1.0

    def test_private_use_char_rejected(self) -> None:
        text, is_valid, score = InvisibleTextScanner().scan("test\ue000input")
        assert not is_valid
        assert text == "testinput"
        assert score == 1.0

    def test_empty_string_passes(self) -> None:
        text, is_valid, score = InvisibleTextScanner().scan("")
        assert is_valid
        assert text == ""
        assert score == 0.0
