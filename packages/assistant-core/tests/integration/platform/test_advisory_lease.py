"""One holder at a time on a named database lock."""

from __future__ import annotations

from assistant_core.platform.lease import advisory_lease


async def test_a_second_holder_of_one_name_is_refused(
    patch_app_db_engine: None,
) -> None:
    del patch_app_db_engine
    async with advisory_lease("sweep") as first, advisory_lease("sweep") as second:
        assert first is True
        assert second is False


async def test_two_names_are_held_at_once(patch_app_db_engine: None) -> None:
    del patch_app_db_engine
    async with advisory_lease("one") as first, advisory_lease("two") as second:
        assert first is True
        assert second is True


async def test_the_name_is_free_again_when_the_holder_leaves(
    patch_app_db_engine: None,
) -> None:
    """The lock is the hold, so the next caller takes it."""
    del patch_app_db_engine
    async with advisory_lease("sweep") as first:
        assert first is True

    async with advisory_lease("sweep") as again:
        assert again is True


async def test_a_refused_caller_does_not_release_the_holders_lock(
    patch_app_db_engine: None,
) -> None:
    del patch_app_db_engine
    async with advisory_lease("sweep") as first:
        async with advisory_lease("sweep") as second:
            assert second is False
        async with advisory_lease("sweep") as third:
            assert third is False
        assert first is True
