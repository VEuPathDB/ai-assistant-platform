from __future__ import annotations

import pytest

from assistant_core.conversation.checkpointer import to_psycopg_url


@pytest.mark.parametrize(
    ("input_url", "expected"),
    [
        (
            "postgresql+asyncpg://u:p@host:5432/db",
            "postgresql://u:p@host:5432/db",
        ),
        (
            "postgresql+psycopg_async://u:p@host:5432/db",
            "postgresql://u:p@host:5432/db",
        ),
        (
            "postgresql://u:p@host:5432/db",
            "postgresql://u:p@host:5432/db",
        ),
    ],
)
def test_to_psycopg_url_strips_async_drivers(input_url: str, expected: str) -> None:
    assert to_psycopg_url(input_url) == expected


def test_to_psycopg_url_preserves_options() -> None:
    src = "postgresql+asyncpg://u:p@host:5432/db?sslmode=require"
    out = to_psycopg_url(src)
    assert out.startswith("postgresql://")
    assert "u:p" in out
    assert "sslmode=require" in out
