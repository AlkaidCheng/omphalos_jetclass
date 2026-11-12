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
from omphjc.tools.madgraph.cards import madspin_card_text, proc_card_commands
from omphjc.tools.madgraph.madspin_card import MadSpinCard
from omphjc.tools.madgraph.proc_card import ProcCard
from omphjc.tools.madgraph.run_card import RunCard

# Commands MadGraph writes at the top of every process card before user input.
_PROC_CARD_PREAMBLE: tuple[str, ...] = (
    "import model sm",
    "define p = g u c d s u~ c~ d~ s~",
    "define j = g u c d s u~ c~ d~ s~",
    "define l+ = e+ mu+",
    "define l- = e- mu-",
    "define vl = ve vm vt",
    "define vl~ = ve~ vm~ vt~",
)

# Official model names that the catalogue provides under a vendored name.
_OFFICIAL_MODEL_ALIASES: dict[str, str] = {"heft-c_mass": "heft_c_mass_jetclass"}


def reference_proc_card(spec: ProcessSpec) -> ProcCard:
    """Return the commands of the reference process card that define the process.

    The ``set`` and ``output`` commands are left out, and so are the commands
    that MadGraph writes at the top of every process card. A card that loads
    no model after those commands uses the Standard Model, so it gets the
    command ``import model sm``. Each model has the name the catalogue gives
    it.

    Raises
    ------
    ValueError
        If `spec` has no reference cards.
    """
    card = ProcCard.read(_reference_dir(spec) / "proc_card_mg5.dat")
    commands = [
        command
        for command in card.commands
        if not command.startswith(("set ", "output"))
    ]
    if tuple(commands[: len(_PROC_CARD_PREAMBLE)]) == _PROC_CARD_PREAMBLE:
        commands = commands[len(_PROC_CARD_PREAMBLE) :]
    if not commands[0].startswith("import model"):
        commands.insert(0, "import model sm")
    return ProcCard(commands=tuple(_canonical_import(command) for command in commands))


def compare_process(spec: ProcessSpec) -> list[Difference]:
    """Return every difference between `spec` and its reference cards.

    Raises
    ------
    ValueError
        If `spec` has no reference cards.
    """
    differences = RunCard.compare_with_reference(spec)
    differences.extend(_compare_proc_card(spec))
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


def _compare_proc_card(spec: ProcessSpec) -> list[Difference]:
    written = ProcCard.from_text(
        "\n".join(proc_card_commands(spec, output_dir=Path(spec.name)))
    )
    card = ProcCard(
        commands=tuple(
            _canonical_import(command)
            for command in written.commands
            if not command.startswith("output ")
        )
    )
    return [
        Difference("proc_card", d.expected, d.actual)
        for d in card.differences(reference_proc_card(spec))
    ]


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


def _canonical_import(line: str) -> str:
    """Reduce an ``import model`` line to the bare catalogue model name."""
    if not line.startswith("import model "):
        return line
    target = line[len("import model ") :].strip()
    name = Path(target).name if "/" in target else target
    return f"import model {_OFFICIAL_MODEL_ALIASES.get(name, name)}"
