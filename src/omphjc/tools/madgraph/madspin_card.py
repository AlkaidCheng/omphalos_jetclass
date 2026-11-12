"""The MadSpin card of MadGraph.

A MadSpin card holds one command on each line, with a comment after ``#``. The
command ``set option value`` gives an option its value, and the command
``decay`` names one decay chain. Two cards with the same options and the same
decay chains give the same decays.
"""

from dataclasses import dataclass
from typing import Any, ClassVar

from omphjc.comparison import Difference
from omphjc.processes.catalogue import ProcessSpec, RunCardValue
from omphjc.processes.input_card import InputCard
from omphjc.tools.madgraph.run_card import format_value, parse_value, values_equal


@dataclass(frozen=True)
class MadSpinCard(InputCard):
    """The options and the decay chains of a MadSpin card.

    Parameters
    ----------
    options : dict[str, RunCardValue]
        The value of each option by its name. Each value is converted with
        :func:`omphjc.tools.madgraph.run_card.parse_value`.
    decays : frozenset[str]
        The decay chains. Each chain is written with one space between its
        words.
    """

    format_name: ClassVar[str] = "madspin_card"
    record_version: ClassVar[int] = 1
    reference_file_name: ClassVar[str] = "madspin_card.dat"

    options: dict[str, RunCardValue]
    decays: frozenset[str]

    @classmethod
    def from_text(cls, text: str) -> "MadSpinCard":
        """Return the options and the decay chains of a card given as text."""
        options = {}
        decays = set()
        for line in text.splitlines():
            words = line.split("#", 1)[0].split()
            if len(words) >= 3 and words[0] == "set":
                options[words[1]] = parse_value(" ".join(words[2:]))
            elif words and words[0] == "decay":
                decays.add(" ".join(words[1:]))
        return cls(options=options, decays=frozenset(decays))

    @classmethod
    def from_process(cls, spec: ProcessSpec) -> "MadSpinCard | None":
        """Return the MadSpin card of `spec`.

        The result is ``None`` for a process without MadSpin.
        """
        return None if spec.madspin_card is None else cls.read(spec.madspin_card)

    def content_record(self) -> dict[str, Any]:
        """Return the options, and the decay chains in sorted order."""
        return {"options": self.options, "decays": sorted(self.decays)}

    def differences(self, reference: "MadSpinCard") -> list[Difference]:
        """Return the differences in the options, then in the decay chains.

        An option is named ``option <name>``. A decay chain that only one
        card holds is named ``decay``, and the chain is its value.
        """
        return [
            *Difference.between_mappings(
                self.options,
                reference.options,
                equal=values_equal,
                text=format_value,
                name="option {}".format,
            ),
            *Difference.between_collections(
                sorted(self.decays), sorted(reference.decays), item="decay"
            ),
        ]
