"""A host that records usage must name who paid, and the type checker says so."""

from pathlib import Path

import pytest
from mypy import api

PACKAGE_ROOT = Path(__file__).resolve().parents[3]

_CALL = """\
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from assistant_core import quota
from assistant_core.platform.types import PaidBy


async def charge(session: AsyncSession) -> None:
    await quota.accumulate(
        session, user_id=uuid4(), tokens=1, cost_usd=Decimal(1){payer}
    )
"""


@pytest.fixture(scope="module")
def mypy_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One cache for the three checks, so the dependencies are read once."""
    return tmp_path_factory.mktemp("mypy_cache")


def _check(tmp_path: Path, cache: Path, payer: str) -> str:
    snippet = tmp_path / "host_charge.py"
    snippet.write_text(_CALL.format(payer=payer))
    stdout, _, _ = api.run(
        [
            "--config-file",
            str(PACKAGE_ROOT / "pyproject.toml"),
            "--cache-dir",
            str(cache),
            str(snippet),
        ],
    )
    return stdout


def test_a_charge_that_names_no_payer_fails_the_type_check(
    tmp_path: Path, mypy_cache: Path
) -> None:
    report = _check(tmp_path, mypy_cache, "")

    assert 'Missing named argument "paid_by" for "accumulate"' in report


def test_a_payer_outside_the_enum_fails_the_type_check(
    tmp_path: Path, mypy_cache: Path
) -> None:
    report = _check(tmp_path, mypy_cache, ', paid_by="user"')

    assert 'Argument "paid_by" to "accumulate" has incompatible type' in report


def test_a_charge_that_names_its_payer_passes_the_type_check(
    tmp_path: Path, mypy_cache: Path
) -> None:
    report = _check(tmp_path, mypy_cache, ", paid_by=PaidBy.USER")

    assert report.startswith("Success"), report
