"""Card, the base class of the formats of the cards that a tool reads."""

from abc import abstractmethod
from pathlib import Path
from typing import ClassVar, TypeVar

from omphjc.comparison import Difference
from omphjc.formats.file_content import FileContent

_CardT = TypeVar("_CardT", bound="Card")


class Card(FileContent):
    """The parsed content of a text file that holds settings or commands.

    A class may also name one card of a tool: the card that the tool's
    program reads in a run. Such a class states the three attributes below.
    A class that describes a format alone leaves them out, and a card of a
    tool that has this format derives from it.

    Attributes
    ----------
    card_name : str
        The name of the card among the cards of its tool, such as
        ``"run_card"``. The record of a task lists the card under this name.
    file_name : str
        The name of the file of the card in the directory where a run keeps
        its cards.
    description : str
        One sentence that says what the card is.
    """

    card_name: ClassVar[str]
    file_name: ClassVar[str]
    description: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_text(cls: type[_CardT], text: str) -> _CardT:
        """Return the content of a card given as text."""

    @classmethod
    def read(cls: type[_CardT], path: Path) -> _CardT:
        """Return the content of the card at `path`, read as UTF-8 text."""
        return cls.from_text(path.read_text(encoding="utf-8"))

    @abstractmethod
    def differences(self: _CardT, reference: _CardT) -> list[Difference]:
        """Return the differences between this card and `reference`.

        Each difference names one part of the content. Its expected value is
        the one of `reference`, and its actual value is the one of this card.
        The layout of a card and its comments give no differences.
        """
