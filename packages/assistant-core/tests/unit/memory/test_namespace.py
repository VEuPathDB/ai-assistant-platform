"""The memory namespace puts the user under the calling application."""

from __future__ import annotations

from uuid import UUID

from assistant_core.memory.store import memory_namespace
from assistant_core.platform.context import application_id_ctx

USER = UUID("11111111-1111-1111-1111-111111111111")


def test_the_namespace_names_the_application_before_the_user() -> None:
    assert memory_namespace(
        application_id="genomics", user_id=USER, kind="strategy"
    ) == (
        "app",
        "genomics",
        "user",
        str(USER),
        "strategy",
    )


def test_the_namespace_defaults_to_the_application_on_the_context() -> None:
    token = application_id_ctx.set("orthology")
    try:
        assert memory_namespace(user_id=USER, kind="knowledge")[1] == "orthology"
    finally:
        application_id_ctx.reset(token)


def test_two_applications_never_share_a_namespace() -> None:
    first = memory_namespace(application_id="a", user_id=USER, kind="gene_set")
    second = memory_namespace(application_id="b", user_id=USER, kind="gene_set")

    assert first != second
