"""The input cards of a catalogue process.

An input card is a card that a tool reads at the start of a run. The
catalogue states the input cards of a process, and the directory of official
cards of that process holds a reference for each of them. An
:class:`InputCard` class returns both cards of a process and compares them,
which is what ``omphjc check-cards`` reports for that class.
"""

from abc import abstractmethod
from pathlib import Path
from typing import ClassVar, TypeVar

from omphjc.comparison import Difference
from omphjc.data_files import Card
from omphjc.processes.catalogue import ProcessSpec

_InputCardT = TypeVar("_InputCardT", bound="InputCard")


class InputCard(Card):
    """A card that a tool reads at the start of a run of a catalogue process.

    The official cards of the process hold a reference for the card.

    Attributes
    ----------
    reference_file_name : str
        The name of the file of the card among the official cards of a
        process, such as ``"run_card.dat"``.
    """

    reference_file_name: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_process(cls: type[_InputCardT], spec: ProcessSpec) -> _InputCardT | None:
        """Return the card that the catalogue states for `spec`.

        The result is ``None`` when the process has no card of this class.
        """

    @classmethod
    def reference(cls: type[_InputCardT], reference_dir: Path) -> _InputCardT | None:
        """Return the card of this class among the official cards of a process.

        The card is read from the file :attr:`reference_file_name`. A class
        whose official card needs more than that overrides this method.

        Parameters
        ----------
        reference_dir : Path
            The directory of the official cards of one process.

        Returns
        -------
        InputCard or None
            The official card, or ``None`` when the directory holds no card
            of this class.
        """
        reference_path = reference_dir / cls.reference_file_name
        return cls.read(reference_path) if reference_path.is_file() else None

    def checked_differences(
        self: _InputCardT, reference: _InputCardT
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
