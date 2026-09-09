"""Importing the scanners without the screening packages names the extra."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Generator

import pytest

from assistant_core.capabilities import piguard

SCREENING_PACKAGES = ("onnxruntime", "tokenizers")


@pytest.fixture(params=SCREENING_PACKAGES)
def absent_package(request: pytest.FixtureRequest) -> Generator[str]:
    name: str = request.param
    saved = sys.modules[name]
    sys.modules[name] = None
    yield name
    sys.modules[name] = saved
    importlib.reload(piguard)


def test_an_absent_screening_package_names_the_extra(absent_package: str) -> None:
    """The import error tells a host which extra it did not declare."""
    with pytest.raises(ModuleNotFoundError) as caught:
        importlib.reload(piguard)

    assert str(caught.value) == (
        "assistant-core[screening] is required to run input screening"
    )
    assert absent_package in str(caught.value.__cause__)
