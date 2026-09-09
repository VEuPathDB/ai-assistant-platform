"""The thread repository: naming, listings scoped by application, and delete."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from tests.conftest import seed_host_user

from assistant_core.conversation.authz import (
    conversation_application_id,
    conversation_assistant_id,
    conversation_owner_id,
)
from assistant_core.persistence.models import Conversation
from assistant_core.persistence.repositories.conversation import (
    DEFAULT_CONVERSATION_NAME,
    ConversationRepository,
)
from assistant_core.platform.context import application_id_ctx
from assistant_core.platform.db import async_session_factory

HOME = "pathfinder"
OTHER = "companion"
SITE = "plasmodb"


@pytest.fixture
def under_home() -> Iterator[None]:
    token = application_id_ctx.set(HOME)
    yield
    application_id_ctx.reset(token)


@pytest.fixture
async def owner(db_cleaner: None, patch_app_db_engine: None) -> UUID:
    del db_cleaner, patch_app_db_engine
    user_id = uuid4()
    await seed_host_user(user_id)
    return user_id


async def _create(
    application_id: str,
    user_id: UUID,
    name: str = "",
    *,
    site_id: str = SITE,
) -> Conversation:
    token = application_id_ctx.set(application_id)
    try:
        async with async_session_factory() as session:
            created = await ConversationRepository(session).create(
                user_id,
                site_id,
                name=name,
            )
            await session.commit()
            return created
    finally:
        application_id_ctx.reset(token)


async def test_a_thread_with_no_name_takes_the_runtime_default(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    created = await _create(HOME, owner)

    assert created.name == DEFAULT_CONVERSATION_NAME
    assert created.application_id == HOME


async def test_a_taken_name_gets_a_numeric_suffix(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    await _create(HOME, owner, "kinases")
    second = await _create(HOME, owner, "kinases")
    third = await _create(HOME, owner, "kinases")

    assert second.name == "kinases (1)"
    assert third.name == "kinases (2)"


async def test_the_same_name_is_free_under_another_application(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    await _create(HOME, owner, "kinases")
    elsewhere = await _create(OTHER, owner, "kinases")

    assert elsewhere.name == "kinases"


async def test_a_listing_shows_only_the_calling_application(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    mine = await _create(HOME, owner, "kinases")
    await _create(OTHER, owner, "proteases")

    async with async_session_factory() as session:
        listed = await ConversationRepository(session).list_active(owner)

    assert [row.id for row in listed] == [mine.id]


async def test_a_listing_is_filtered_by_site(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    plasmo = await _create(HOME, owner, "kinases")
    await _create(HOME, owner, "amoeba work", site_id="amoebadb")

    async with async_session_factory() as session:
        listed = await ConversationRepository(session).list_active(owner, site_id=SITE)

    assert [row.id for row in listed] == [plasmo.id]


async def test_a_dismissed_thread_moves_between_the_two_listings(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    created = await _create(HOME, owner, "kinases")

    async with async_session_factory() as session:
        repo = ConversationRepository(session)
        await repo.dismiss(created.id)
        await session.commit()
        active = await repo.list_active(owner)
        dismissed = await repo.list_dismissed(owner)

    assert active == []
    assert [row.id for row in dismissed] == [created.id]

    async with async_session_factory() as session:
        repo = ConversationRepository(session)
        await repo.restore(created.id)
        await session.commit()
        active = await repo.list_active(owner)
        dismissed = await repo.list_dismissed(owner)

    assert [row.id for row in active] == [created.id]
    assert dismissed == []


async def test_a_rename_is_deduplicated_and_reported(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    await _create(HOME, owner, "kinases")
    second = await _create(HOME, owner, "proteases")

    async with async_session_factory() as session:
        repo = ConversationRepository(session)
        stored = await repo.update_thread(second.id, name="kinases")
        await session.commit()
        renamed = await repo.get_by_id(second.id)

    assert stored == "kinases (1)"
    assert renamed is not None
    assert renamed.name == "kinases (1)"


async def test_a_delete_lifts_the_children_to_the_deleted_parent(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    root = await _create(HOME, owner, "root")
    middle = await _create(HOME, owner, "middle")
    leaf = await _create(HOME, owner, "leaf")

    async with async_session_factory() as session:
        await session.execute(
            Conversation.__table__.update()
            .where(Conversation.id == middle.id)
            .values(parent_conversation_id=root.id),
        )
        await session.execute(
            Conversation.__table__.update()
            .where(Conversation.id == leaf.id)
            .values(parent_conversation_id=middle.id),
        )
        await session.commit()

    async with async_session_factory() as session:
        repo = ConversationRepository(session)
        await repo.delete(middle.id)
        await session.commit()
        survivors = {
            row.id: row.parent_conversation_id for row in await repo.list_active(owner)
        }

    assert set(survivors) == {root.id, leaf.id}
    assert survivors[leaf.id] == root.id


async def test_a_cascading_delete_takes_the_whole_subtree(
    owner: UUID,
    under_home: None,
) -> None:
    del under_home
    root = await _create(HOME, owner, "root")
    middle = await _create(HOME, owner, "middle")
    leaf = await _create(HOME, owner, "leaf")

    async with async_session_factory() as session:
        await session.execute(
            Conversation.__table__.update()
            .where(Conversation.id == middle.id)
            .values(parent_conversation_id=root.id),
        )
        await session.execute(
            Conversation.__table__.update()
            .where(Conversation.id == leaf.id)
            .values(parent_conversation_id=middle.id),
        )
        await session.commit()

    async with async_session_factory() as session:
        repo = ConversationRepository(session)
        await repo.delete(middle.id, cascade=True)
        await session.commit()
        survivors = [row.id for row in await repo.list_active(owner)]

    assert survivors == [root.id]


async def test_a_worker_reads_the_owner_the_assistant_and_the_application(
    owner: UUID,
    under_home: None,
) -> None:
    """A job runs as the row says, whatever context it started in."""
    del under_home
    created = await _create(OTHER, owner, "kinases")

    assert await conversation_owner_id(created.id) == owner
    assert await conversation_application_id(created.id) == OTHER
    assert await conversation_assistant_id(created.id) == "default"


async def test_a_thread_that_is_gone_reads_as_nothing(
    owner: UUID,
    under_home: None,
) -> None:
    del owner, under_home
    missing = uuid4()

    assert await conversation_owner_id(missing) is None
    assert await conversation_application_id(missing) is None
    assert await conversation_assistant_id(missing) is None
