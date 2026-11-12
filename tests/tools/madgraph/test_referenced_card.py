from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ClassVar

import pytest

from omphjc.comparison import Difference
from omphjc.processes import ProcessSpec
from omphjc.tools.madgraph.referenced_card import ReferencedCard


@dataclass(frozen=True)
class DefinitionsCard(ReferencedCard):
    """A card with one multiparticle definition on each line.

    A process without definitions has no such card. The official card is the
    file ``definitions.dat``.
    """

    format_name: ClassVar[str] = "definitions_card"
    record_version: ClassVar[int] = 1
    reference_file_name: ClassVar[str] = "definitions.dat"

    definitions: tuple[str, ...]

    @classmethod
    def from_text(cls, text: str) -> "DefinitionsCard":
        return cls(definitions=tuple(line for line in text.splitlines() if line))

    def content_record(self) -> list[str]:
        return list(self.definitions)

    def differences(self, reference: "DefinitionsCard") -> list[Difference]:
        return Difference.between_collections(
            self.definitions, reference.definitions, item="definition"
        )

    @classmethod
    def from_process(cls, spec: ProcessSpec) -> "DefinitionsCard | None":
        return cls(definitions=spec.definitions) if spec.definitions else None


@pytest.fixture
def spec(specs: Mapping[str, ProcessSpec], tmp_path: Path) -> ProcessSpec:
    """A process with two definitions and an empty directory of official cards."""
    return replace(
        specs["HToBB"],
        definitions=("p = p b b~", "j = j b b~"),
        reference_cards=tmp_path,
    )


def test_each_item_starts_with_the_name_of_the_card(spec: ProcessSpec) -> None:
    assert spec.reference_cards is not None
    (spec.reference_cards / "definitions.dat").write_text(
        "p = p b b~\nj = j\n", encoding="utf-8"
    )
    assert [str(d) for d in DefinitionsCard.compare_with_reference(spec)] == [
        "missing definitions_card.definition: j = j",
        "unexpected definitions_card.definition: j = j b b~",
    ]


def test_a_card_equal_to_its_reference_gives_no_difference(spec: ProcessSpec) -> None:
    assert spec.reference_cards is not None
    (spec.reference_cards / "definitions.dat").write_text(
        "p = p b b~\nj = j b b~\n", encoding="utf-8"
    )
    assert DefinitionsCard.compare_with_reference(spec) == []


def test_a_card_of_the_reference_alone_is_missing(spec: ProcessSpec) -> None:
    assert spec.reference_cards is not None
    (spec.reference_cards / "definitions.dat").write_text(
        "p = p b b~\n", encoding="utf-8"
    )
    differences = DefinitionsCard.compare_with_reference(replace(spec, definitions=()))
    assert [str(d) for d in differences] == ["missing card: definitions_card"]


def test_a_card_of_the_process_alone_is_unexpected(spec: ProcessSpec) -> None:
    differences = DefinitionsCard.compare_with_reference(spec)
    assert [str(d) for d in differences] == ["unexpected card: definitions_card"]


def test_a_card_that_neither_side_has_gives_no_difference(spec: ProcessSpec) -> None:
    assert DefinitionsCard.compare_with_reference(replace(spec, definitions=())) == []


def test_a_process_without_reference_cards_is_refused(spec: ProcessSpec) -> None:
    with pytest.raises(ValueError, match="no reference cards"):
        DefinitionsCard.compare_with_reference(replace(spec, reference_cards=None))
