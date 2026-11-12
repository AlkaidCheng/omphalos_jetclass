"""Compare catalogue entries with their reference cards (``omphjc check-cards``).

The reference of a JetClass process is its official gridpack cards: a run card
and a launch script with ``set`` overrides, a process card and, for the top
processes, a MadSpin card. The comparison reports, value by value, every
setting an entry applies that differs from its reference and every tracked
reference setting the entry leaves out. Entries without reference cards are
not compared.
"""

from collections.abc import Iterable
from pathlib import Path

from omphjc.comparison import Difference
from omphjc.processes.catalogue import ProcessSpec, default_catalogue
from omphjc.tools.madgraph.cards import madspin_card_text
from omphjc.tools.madgraph.madspin_card import MadSpinCard
from omphjc.tools.madgraph.proc_card import ProcCard
from omphjc.tools.madgraph.run_card import RunCard


def compare_process(spec: ProcessSpec) -> list[Difference]:
    """Return every difference between `spec` and its reference cards.

    Raises
    ------
    ValueError
        If `spec` has no reference cards.
    """
    differences = RunCard.compare_with_reference(spec)
    differences.extend(ProcCard.compare_with_reference(spec))
    differences.extend(_compare_madspin(spec))
    return differences


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


def _reference_dir(spec: ProcessSpec) -> Path:
    if spec.reference_cards is None:
        raise ValueError(f"Process {spec.name!r} has no reference cards")
    return spec.reference_cards


def _compare_madspin(spec: ProcessSpec) -> list[Difference]:
    reference_path = _reference_dir(spec) / "madspin_card.dat"
    if reference_path.is_file() != spec.uses_madspin:
        return [
            Difference("madspin", str(reference_path.is_file()), str(spec.uses_madspin))
        ]
    if not spec.uses_madspin:
        return []
    card = MadSpinCard.from_text(madspin_card_text(spec))
    return [
        Difference(f"madspin {d.item}", d.expected, d.actual)
        for d in card.differences(MadSpinCard.read(reference_path))
    ]
