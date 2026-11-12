"""Compare catalogue entries with their reference cards (``omphjc check-cards``).

The reference cards of a process are its official JetClass cards. Each card
class in :data:`INPUT_CARDS` compares the card that the catalogue states for a
process with the official one. Entries without reference cards are not
compared.
"""

from collections.abc import Iterable

from omphjc.comparison import Difference
from omphjc.processes.catalogue import ProcessSpec, default_catalogue
from omphjc.processes.input_card import InputCard
from omphjc.tools.madgraph.madspin_card import MadSpinCard
from omphjc.tools.madgraph.proc_card import ProcCard
from omphjc.tools.madgraph.run_card import RunCard

INPUT_CARDS: tuple[type[InputCard], ...] = (RunCard, ProcCard, MadSpinCard)
"""The card classes that are compared, in the order of a report."""


def compare_process(spec: ProcessSpec) -> list[Difference]:
    """Return every difference between `spec` and its reference cards.

    The differences come card by card, in the order of :data:`INPUT_CARDS`.

    Raises
    ------
    ValueError
        If `spec` has no reference cards.
    """
    return [
        difference
        for card_class in INPUT_CARDS
        for difference in card_class.compare_with_reference(spec)
    ]


def compare_all(
    specs: Iterable[ProcessSpec] | None = None,
) -> dict[str, list[Difference]]:
    """Return the differences of every process that has reference cards.

    The result maps the name of a process to its differences, in the order
    of the catalogue. A process that matches its reference cards is absent
    from the result, so an empty result means that every compared process
    matches. Without `specs`, the processes of the default catalogue are
    compared.
    """
    differences = {}
    for spec in default_catalogue().values() if specs is None else specs:
        if spec.reference_cards is None:
            continue
        if process_differences := compare_process(spec):
            differences[spec.name] = process_differences
    return differences
