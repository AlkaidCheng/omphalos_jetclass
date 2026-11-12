"""Compare catalogue entries with their reference cards (``omphjc check-cards``).

The reference of a JetClass process is its official gridpack cards: a run card
and a launch script with ``set`` overrides, a process card and, for the top
processes, a MadSpin card. Each card class in :data:`REFERENCED_CARDS`
compares the card that the catalogue states for a process with the official
one. Entries without reference cards are not compared.
"""

from collections.abc import Iterable

from omphjc.comparison import Difference
from omphjc.processes.catalogue import ProcessSpec, default_catalogue
from omphjc.tools.madgraph.madspin_card import MadSpinCard
from omphjc.tools.madgraph.proc_card import ProcCard
from omphjc.tools.madgraph.referenced_card import ReferencedCard
from omphjc.tools.madgraph.run_card import RunCard

REFERENCED_CARDS: tuple[type[ReferencedCard], ...] = (RunCard, ProcCard, MadSpinCard)
"""The card classes that are compared, in the order of a report."""


def compare_process(spec: ProcessSpec) -> list[Difference]:
    """Return every difference between `spec` and its reference cards.

    The differences come card by card, in the order of
    :data:`REFERENCED_CARDS`.

    Raises
    ------
    ValueError
        If `spec` has no reference cards.
    """
    return [
        difference
        for card_class in REFERENCED_CARDS
        for difference in card_class.compare_with_reference(spec)
    ]


def compare_all(
    specs: Iterable[ProcessSpec] | None = None,
) -> dict[str, list[Difference]]:
    """Return the differences of every process that has reference cards.

    The result maps a process name to its differences, in catalogue order;
    a process that matches its reference cards is absent, so an empty result
    means every compared process matches. Without `specs`, the processes of
    the default catalogue are compared.
    """
    differences = {}
    for spec in default_catalogue().values() if specs is None else specs:
        if spec.reference_cards is None:
            continue
        if process_differences := compare_process(spec):
            differences[spec.name] = process_differences
    return differences
