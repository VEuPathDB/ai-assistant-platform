"""The built wheel offers input screening as an extra, and only as an extra."""

import zipfile
from email.message import Message
from importlib.metadata import PathDistribution
from pathlib import Path

import pytest

SCREENING_MARKER = "extra == 'screening'"


def _requirements(metadata: Message) -> list[tuple[str, str]]:
    """Answer every ``Requires-Dist`` as its requirement and its marker."""
    parsed = []
    for line in metadata.get_all("Requires-Dist") or []:
        requirement, _, marker = line.partition(";")
        parsed.append((requirement.strip(), marker.strip().replace('"', "'")))
    return parsed


@pytest.fixture(scope="module")
def wheel_metadata(
    built_wheel: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Message:
    unpacked = tmp_path_factory.mktemp("metadata")
    with zipfile.ZipFile(built_wheel) as archive:
        entries = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        assert len(entries) == 1, f"expected one METADATA, found {entries}"
        archive.extract(entries[0], unpacked)
    return PathDistribution(unpacked / Path(entries[0]).parent).metadata


@pytest.mark.wheel
def test_the_wheel_offers_the_screening_extra(wheel_metadata: Message) -> None:
    """A host that screens input has an extra to name."""
    assert wheel_metadata.get_all("Provides-Extra") == ["screening"]


@pytest.mark.wheel
def test_the_screening_packages_ride_the_extra(wheel_metadata: Message) -> None:
    """The extra is what pulls the ONNX runtime and the tokenizer."""
    behind_the_extra = sorted(
        requirement
        for requirement, marker in _requirements(wheel_metadata)
        if marker == SCREENING_MARKER
    )

    assert behind_the_extra == ["onnxruntime>=1.19.0", "tokenizers>=0.21.0"]


@pytest.mark.wheel
def test_an_unscreened_install_carries_neither(wheel_metadata: Message) -> None:
    """An assistant that screens nothing installs no ONNX runtime."""
    unconditional = [
        requirement
        for requirement, marker in _requirements(wheel_metadata)
        if not marker
    ]

    assert [
        requirement
        for requirement in unconditional
        if requirement.startswith(("onnxruntime", "tokenizers"))
    ] == []
