"""The ownership helpers scope a thread by user and application."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest

from assistant_core.conversation.authz import (
    get_owned_conversation,
    get_visible_conversation,
)
from assistant_core.errors import (
    ConversationForbiddenError,
    ConversationNotFoundError,
)
from assistant_core.persistence.models import Conversation
from assistant_core.persistence.repositories.conversation import ConversationRepository
from assistant_core.platform.context import application_id_ctx

OWNER = UUID("22222222-2222-2222-2222-222222222222")
STRANGER = UUID("33333333-3333-3333-3333-333333333333")
HOME = "pathfinder"
OTHER = "genomics"


@pytest.fixture(autouse=True)
def calling_application() -> Iterator[None]:
    """A served request names this application, the way security does."""
    token = application_id_ctx.set(HOME)
    try:
        yield
    finally:
        application_id_ctx.reset(token)


class OneRowRepository:
    """Answers every lookup with the same row, without a database."""

    def __init__(self, conversation: Conversation | None) -> None:
        self.conversation = conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        del conversation_id
        return self.conversation


def _repo(application_id: str) -> OneRowRepository:
    return OneRowRepository(
        Conversation(
            id=uuid4(),
            user_id=OWNER,
            site_id="plasmodb",
            name="kinases",
            application_id=application_id,
        ),
    )


def test_the_helpers_take_a_lookup_that_is_not_the_repository() -> None:
    """The helpers read one method, so any lookup a host holds fits them."""
    assert ConversationRepository not in type(_repo(HOME)).__mro__


async def test_the_owner_reaches_a_thread_of_the_calling_application() -> None:
    found = await get_visible_conversation(_repo(HOME), uuid4(), OWNER)

    assert found.user_id == OWNER


async def test_the_same_user_under_another_application_is_told_nothing() -> None:
    with pytest.raises(ConversationNotFoundError):
        await get_visible_conversation(_repo(OTHER), uuid4(), OWNER)


async def test_another_user_under_this_application_is_told_nothing() -> None:
    with pytest.raises(ConversationNotFoundError):
        await get_visible_conversation(_repo(HOME), uuid4(), STRANGER)


async def test_the_forbidding_helper_also_refuses_another_application() -> None:
    with pytest.raises(ConversationForbiddenError):
        await get_owned_conversation(_repo(OTHER), uuid4(), OWNER)


async def test_the_forbidding_helper_separates_missing_from_not_yours() -> None:
    """A caller who owns nothing learns the difference; a stranger does not."""
    with pytest.raises(ConversationNotFoundError):
        await get_owned_conversation(OneRowRepository(None), uuid4(), OWNER)


async def test_the_calling_application_comes_from_the_context() -> None:
    token = application_id_ctx.set(OTHER)
    try:
        found = await get_visible_conversation(_repo(OTHER), uuid4(), OWNER)
    finally:
        application_id_ctx.reset(token)

    assert found.application_id == OTHER


async def test_a_missing_error_names_the_thread_that_was_asked_for() -> None:
    conversation_id = uuid4()

    with pytest.raises(ConversationNotFoundError) as caught:
        await get_visible_conversation(OneRowRepository(None), conversation_id, OWNER)

    assert caught.value.conversation_id == conversation_id
