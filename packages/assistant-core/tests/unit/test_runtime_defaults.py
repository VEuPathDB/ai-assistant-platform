"""The runtime's own defaults name no product."""

from __future__ import annotations

from assistant_core.persistence.models import DEFAULT_ASSISTANT_ID, Conversation
from assistant_core.platform.context import (
    DEFAULT_APPLICATION_ID,
    application_id_ctx,
    calling_application,
)


def test_the_default_application_is_not_a_product_name() -> None:
    assert DEFAULT_APPLICATION_ID == "default"


def test_the_default_assistant_is_not_a_product_name() -> None:
    assert DEFAULT_ASSISTANT_ID == "default"


def test_a_call_that_names_no_application_acts_as_the_default() -> None:
    assert calling_application() == "default"


def test_a_call_that_names_an_application_acts_as_it() -> None:
    token = application_id_ctx.set("some-host")
    try:
        assert calling_application() == "some-host"
    finally:
        application_id_ctx.reset(token)


def test_the_stored_column_defaults_are_the_neutral_ids() -> None:
    columns = Conversation.__table__.columns

    assert columns["application_id"].server_default.arg == "default"
    assert columns["assistant_id"].server_default.arg == "default"
