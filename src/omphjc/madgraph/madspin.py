"""Read and compare MadSpin cards.

A MadSpin card holds ``set option value`` lines and ``decay`` chains, with
comments after ``#``. Two cards with the same options and the same set of
decay chains configure the same decays, whatever their layout.
"""

from dataclasses import dataclass

from omphjc.madgraph.runcard import format_value, parse_value, values_equal
from omphjc.processes.catalogue import RunCardValue


@dataclass(frozen=True)
class MadSpinCard:
    """The configuration of a MadSpin card."""

    options: dict[str, RunCardValue]
    decays: frozenset[str]


@dataclass(frozen=True)
class MadSpinDifference:
    """One configuration difference between two MadSpin cards."""

    item: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return f"{self.item}: expected {self.expected}, got {self.actual}"


def parse_madspin_card(text: str) -> MadSpinCard:
    """Return the options and decay chains of a MadSpin card.

    Decay chains are normalised to single spaces between tokens.
    """
    options: dict[str, RunCardValue] = {}
    decays: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        tokens = line.split()
        if tokens[0] == "set" and len(tokens) >= 3:
            options[tokens[1]] = parse_value(" ".join(tokens[2:]))
        elif tokens[0] == "decay":
            decays.add(" ".join(tokens[1:]))
    return MadSpinCard(options=options, decays=frozenset(decays))


def compare_madspin_cards(
    card: MadSpinCard, reference: MadSpinCard
) -> list[MadSpinDifference]:
    """Return every difference between `card` and `reference`."""
    differences = []
    for name in sorted(card.options.keys() | reference.options.keys()):
        if name not in reference.options:
            differences.append(
                MadSpinDifference(
                    f"option {name}", "absent", format_value(card.options[name])
                )
            )
        elif name not in card.options:
            differences.append(
                MadSpinDifference(
                    f"option {name}", format_value(reference.options[name]), "absent"
                )
            )
        elif not values_equal(card.options[name], reference.options[name]):
            differences.append(
                MadSpinDifference(
                    f"option {name}",
                    format_value(reference.options[name]),
                    format_value(card.options[name]),
                )
            )
    for decay in sorted(reference.decays - card.decays):
        differences.append(MadSpinDifference(f"decay {decay}", "present", "absent"))
    for decay in sorted(card.decays - reference.decays):
        differences.append(MadSpinDifference(f"decay {decay}", "absent", "present"))
    return differences
