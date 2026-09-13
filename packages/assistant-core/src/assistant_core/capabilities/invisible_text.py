"""The Unicode half of screening: text that hides characters from a reader."""

from __future__ import annotations

import unicodedata

# Unicode categories that indicate invisible / control characters.
_INVISIBLE_CATEGORIES = frozenset({"Cf", "Co", "Cn"})


class InvisibleTextScanner:
    """Detect and remove invisible Unicode characters.

    Format, private-use and unassigned characters count as invisible.
    """

    def scan(self, text: str) -> tuple[str, bool, float]:
        """The cleaned text, whether it passes, and the risk it carries."""
        # ASCII text has no invisible characters.
        if text.isascii():
            return text, True, 0.0

        has_invisible = any(
            unicodedata.category(ch) in _INVISIBLE_CATEGORIES for ch in text
        )
        if not has_invisible:
            return text, True, 0.0

        cleaned = "".join(
            ch for ch in text if unicodedata.category(ch) not in _INVISIBLE_CATEGORIES
        )
        return cleaned, False, 1.0
