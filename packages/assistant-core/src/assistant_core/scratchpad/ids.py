"""The id a note carries and the token size the budget gate reads."""

from __future__ import annotations

import secrets


def mint_note_id() -> str:
    """A short id the model can quote back. Uniqueness is the database's."""
    return f"n-{secrets.token_hex(3)}"


def approx_body_tokens(body: str) -> int:
    """Token count from character count. Deterministic and stdlib only.

    The budget gate is coarse, so an error of a fifth changes no decision.
    """
    return len(body) // 4
