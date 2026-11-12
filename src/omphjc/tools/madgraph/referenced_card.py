"""The MadGraph cards that have a reference among the official cards.

The catalogue states the cards of a process, and the directory of official
cards of that process holds the references. A :class:`ReferencedCard` class
returns both cards of a process and compares them, which is what ``omphjc
check-cards`` reports for that class.
"""

from abc import abstractmethod
from pathlib import Path
from typing import TypeVar

from omphjc.comparison import Difference
from omphjc.data_files import Card
from omphjc.processes.catalogue import ProcessSpec

_ReferencedCardT = TypeVar("_ReferencedCardT", bound="ReferencedCard")


class ReferencedCard(Card):
    """A MadGraph card of a catalogue process that has an official card."""

    @classmethod
    @abstractmethod
    def from_process(
        cls: type[_ReferencedCardT], spec: ProcessSpec
    ) -> _ReferencedCardT | None:
        """Return the card that the catalogue states for `spec`.

        The result is ``None`` when the process has no card of this class.
        """

    @classmethod
    @abstractmethod
    def reference(
        cls: type[_ReferencedCardT], reference_dir: Path
    ) -> _ReferencedCardT | None:
        """Return the card of this class among the official cards of a process.

        Parameters
        ----------
        reference_dir : Path
            The directory of the official cards of one process.

        Returns
        -------
        ReferencedCard or None
            The official card, or ``None`` when the directory holds no card
            of this class.
        """

    def checked_differences(
        self: _ReferencedCardT, reference: _ReferencedCardT
    ) -> list[Difference]:
        """Return the differences from `reference` that a check reports.

        These are the differences of :meth:`differences`. A class that
        leaves some of them out of a check overrides this method.
        """
        return self.differences(reference)

    @classmethod
    def compare_with_reference(cls, spec: ProcessSpec) -> list[Difference]:
        """Return the differences between the card of `spec` and its reference.

        The item of each difference starts with :attr:`format_name` and a
        dot. A card that only one side has gives one difference with the item
        ``card``, whose value is :attr:`format_name`.

        Raises
        ------
        ValueError
            If `spec` has no reference cards.
        """
        if spec.reference_cards is None:
            raise ValueError(f"Process {spec.name!r} has no reference cards")
        card = cls.from_process(spec)
        reference = cls.reference(spec.reference_cards)
        if card is None and reference is None:
            return []
        if card is None:
            return [Difference("card", cls.format_name, None)]
        if reference is None:
            return [Difference("card", None, cls.format_name)]
        return [
            Difference(f"{cls.format_name}.{d.item}", d.expected, d.actual)
            for d in card.checked_differences(reference)
        ]
