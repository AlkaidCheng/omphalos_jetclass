"""The parameter card of MadGraph, a file in the SLHA format.

The SUSY Les Houches Accord (SLHA, https://arxiv.org/abs/hep-ph/0311123) is a
text format for the parameters of a model. A ``block`` line names a group of
parameters, and each line after it holds one parameter: its indices, then its
value. A ``decay`` line holds the width of a particle, and each line after it
holds one decay channel of that particle. Text after ``#`` is a comment.
"""

import json
from dataclasses import dataclass
from typing import ClassVar

from omphjc.comparison import Difference
from omphjc.data_files import Card
from omphjc.processes.catalogue import RunCardValue
from omphjc.tools.madgraph.run_card import parse_value

# The first word of a line that starts a block or a decay table. MadGraph puts
# every line in lower case before it looks for these words (ParamCard.read,
# https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/models/check_param_card.py#L351-L371).
_TABLE_KEYWORDS = ("block", "decay")


@dataclass(frozen=True)
class SLHACard(Card):
    """The entries of a parameter card.

    Parameters
    ----------
    entries : tuple[tuple[RunCardValue, ...], ...]
        One entry for each line of the card, in the order of the card. An
        entry holds the words of its line in lower case, each converted with
        :func:`omphjc.tools.madgraph.run_card.parse_value`. The entry of a
        line inside a block or a decay table starts with the words of the
        ``block`` or ``decay`` line above it, so the same line in two blocks
        gives two different entries.
    """

    format_name: ClassVar[str] = "slha"
    record_version: ClassVar[int] = 1

    entries: tuple[tuple[RunCardValue, ...], ...]

    @classmethod
    def from_text(cls, text: str) -> "SLHACard":
        """Return the entries of a parameter card given as text."""
        entries = []
        table: tuple[RunCardValue, ...] = ()
        for line in text.splitlines():
            words = line.split("#", 1)[0].lower().split()
            row = tuple(parse_value(word) for word in words)
            if row and row[0] in _TABLE_KEYWORDS:
                table = row
                entries.append(row)
            elif row:
                entries.append(table + row)
        return cls(entries=tuple(entries))

    def content_record(self) -> list[list[RunCardValue]]:
        """Return the entries in sorted order.

        The order of the lines in the card does not change the record.
        """
        return [list(entry) for entry in sorted(self.entries, key=json.dumps)]

    def differences(self, reference: "SLHACard") -> list[Difference]:
        """Return one difference for each entry that only one card holds.

        The value of a difference is the words of the entry. An entry with
        another value in `reference` gives two differences, one for each
        value.
        """
        return Difference.between_collections(
            self.content_record(),
            reference.content_record(),
            item="entry",
            text=lambda entry: " ".join(str(word) for word in entry),
        )


class ParamCard(SLHACard):
    """The parameter card of a MadGraph run, which has the SLHA format."""

    card_name: ClassVar[str] = "param_card"
    file_name: ClassVar[str] = "param_card.dat"
    description: ClassVar[str] = "The parameter card of the model."
