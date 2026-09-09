"""The chain's refusals, and the filter that scopes autogenerate."""

import pytest
from alembic.script import Script, ScriptDirectory

from assistant_core.migrate import OWNED_TABLES, alembic_config, include_object

BASELINE = "2026_09_09_0001"
STOP_AND_COST = "2026_09_09_0002"


def _revisions() -> list[Script]:
    return list(ScriptDirectory.from_config(alembic_config()).walk_revisions())


def test_the_baseline_refuses_to_drop_tables_a_host_chain_may_have_built() -> None:
    baseline = ScriptDirectory.from_config(alembic_config()).get_revision(BASELINE)
    assert baseline is not None

    with pytest.raises(NotImplementedError, match="baseline"):
        baseline.module.downgrade()


def test_the_filter_keeps_every_table_this_distribution_owns() -> None:
    kept = [
        name for name in OWNED_TABLES if include_object(None, name, "table", True, None)
    ]

    assert kept == list(OWNED_TABLES)


def test_the_filter_drops_a_table_the_host_owns() -> None:
    assert include_object(None, "users", "table", True, None) is False
    assert include_object(None, "background_tasks", "table", True, None) is False
    assert include_object(None, "gene_sets", "table", True, None) is False


def test_the_filter_leaves_every_other_kind_to_its_table() -> None:
    """A table that passes has its columns and constraints compared."""
    assert include_object(None, "assistant_id", "column", False, None) is True
    assert include_object(None, "ck_messages_role", "unique_constraint", True, None)


def test_the_stop_and_cost_revision_also_refuses_to_drop_its_tables() -> None:
    revision = ScriptDirectory.from_config(alembic_config()).get_revision(STOP_AND_COST)
    assert revision is not None

    with pytest.raises(NotImplementedError, match="host chain built"):
        revision.module.downgrade()


def test_every_revision_names_the_tables_it_creates() -> None:
    """A revision that forgets CREATES is refused by name, not by AttributeError."""
    for revision in _revisions():
        assert "CREATES" in vars(revision.module), (
            f"revision {revision.revision} at {revision.path} declares no CREATES"
        )


def test_every_table_a_revision_creates_is_a_table_this_chain_owns() -> None:
    """OWNED_TABLES grows with the chain; a revision freezes what it created."""
    created: set[str] = set()
    for revision in _revisions():
        created |= set(revision.module.CREATES)

    assert created == set(OWNED_TABLES)


def test_no_two_revisions_create_the_same_table() -> None:
    counted = [name for rev in _revisions() for name in rev.module.CREATES]

    assert sorted(counted) == sorted(OWNED_TABLES)
