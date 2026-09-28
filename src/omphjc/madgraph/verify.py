"""Check the catalogue against its reference cards.

The reference cards of the JetClass processes are the official gridpack cards:
MadGraph 3.1.1 templates with the values filled in, plus a launch script with a
few overrides, while this package applies its settings at launch. The
comparison is therefore made value by value: every setting the catalogue
applies must equal the reference one, and every tracked reference setting must
be applied by the catalogue. Processes without reference cards are not checked.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from omphjc.madgraph.cards import madspin_card_text, proc_card_commands
from omphjc.madgraph.madspin import compare_madspin_cards, parse_madspin_card
from omphjc.madgraph.runcard import (
    format_value,
    parse_launch_overrides,
    parse_run_card,
    values_equal,
)
from omphjc.processes.catalogue import ProcessSpec, RunCardValue, catalogue

TRACKED_PARAMETERS: frozenset[str] = frozenset(
    {
        # beams and PDF
        "lpp1",
        "lpp2",
        "ebeam1",
        "ebeam2",
        "pdlabel",
        "lhaid",
        # scales
        "fixed_ren_scale",
        "fixed_fac_scale",
        "dynamical_scale_choice",
        "scalefact",
        # flavour scheme, widths, systematics
        "maxjetflavor",
        "bwcutoff",
        "use_syst",
        "cut_decays",
        # generator-level cuts
        "ptj",
        "ptl",
        "etaj",
        "etal",
        "drjj",
        "drjl",
        "drll",
        "misset",
        "pt_min_pdg",
        "eta_max_pdg",
        "ptheavy",
        # MLM matching
        "ickkw",
        "xqcut",
        "auto_ptj_mjj",
        "alpsfact",
        "asrwgtflavor",
    }
)
"""Run-card parameters that carry physics and must match the reference cards.

Parameters left out are MadGraph internals (run tag, event count, seed,
integration strategy, event normalisation, bias modules, systematics program
arguments) or cut maxima left at their disabled default in every official card.
"""

DISABLED_DEFAULTS: dict[str, RunCardValue] = {
    "pt_min_pdg": {},
    "eta_max_pdg": {},
    "ptheavy": 0.0,
}
"""Values at which a tracked cut is switched off.

The catalogue only lists active physics, so a tracked parameter that the
reference card leaves at one of these values needs no catalogue entry.
"""

# Lines MadGraph writes at the top of every process card before user input.
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


@dataclass(frozen=True)
class Mismatch:
    """One difference between the catalogue and the reference cards."""

    process: str
    item: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return (
            f"{self.process}: {self.item}: expected {self.expected}, "
            f"got {self.actual}"
        )


def reference_run_settings(spec: ProcessSpec) -> dict[str, RunCardValue]:
    """Return the reference run-card values with the launch overrides applied.

    The overrides are the ``set`` lines of the ``run_*.mg5`` launch scripts in
    the reference directory.

    Raises
    ------
    ValueError
        If `spec` has no reference cards.
    """
    directory = _reference_dir(spec)
    settings = parse_run_card((directory / "run_card.dat").read_text("utf-8"))
    for launcher in sorted(directory.glob("run_*.mg5")):
        settings.update(parse_launch_overrides(launcher.read_text("utf-8")))
    return settings


def reference_proc_lines(spec: ProcessSpec) -> list[str]:
    """Return the reference process definition without MadGraph's preamble.

    The ``set`` option lines, comments and the ``output`` line are dropped;
    a card that never imports a model after the preamble is standard-model.

    Raises
    ------
    ValueError
        If `spec` has no reference cards.
    """
    text = (_reference_dir(spec) / "proc_card_mg5.dat").read_text("utf-8")
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "set ", "output"))
    ]
    if tuple(lines[: len(_PROC_CARD_PREAMBLE)]) == _PROC_CARD_PREAMBLE:
        lines = lines[len(_PROC_CARD_PREAMBLE) :]
    if not lines[0].startswith("import model"):
        lines.insert(0, "import model sm")
    return [_canonical_import(line) for line in lines]


def compare_process(spec: ProcessSpec) -> list[Mismatch]:
    """Return every difference between `spec` and its reference cards.

    Raises
    ------
    ValueError
        If `spec` has no reference cards.
    """
    mismatches = _compare_run_card(spec)
    mismatches.extend(_compare_proc_card(spec))
    mismatches.extend(_compare_madspin(spec))
    return mismatches


def compare_all(specs: Iterable[ProcessSpec] | None = None) -> list[Mismatch]:
    """Return the differences for every process that has reference cards.

    `specs` defaults to the shipped catalogue.
    """
    return [
        mismatch
        for spec in (catalogue().values() if specs is None else specs)
        if spec.reference_cards is not None
        for mismatch in compare_process(spec)
    ]


def _reference_dir(spec: ProcessSpec) -> Path:
    if spec.reference_cards is None:
        raise ValueError(f"Process {spec.name!r} has no reference cards")
    return spec.reference_cards


def _compare_run_card(spec: ProcessSpec) -> list[Mismatch]:
    reference = reference_run_settings(spec)
    mismatches = []
    for name, value in spec.run_card.items():
        if name not in reference:
            mismatches.append(
                Mismatch(spec.name, f"run_card.{name}", "absent", format_value(value))
            )
        elif not values_equal(value, reference[name]):
            mismatches.append(
                Mismatch(
                    spec.name,
                    f"run_card.{name}",
                    format_value(reference[name]),
                    format_value(value),
                )
            )
    untracked = TRACKED_PARAMETERS & (reference.keys() - spec.run_card.keys())
    for name in sorted(untracked):
        if name in DISABLED_DEFAULTS and values_equal(
            reference[name], DISABLED_DEFAULTS[name]
        ):
            continue
        mismatches.append(
            Mismatch(
                spec.name, f"run_card.{name}", format_value(reference[name]), "absent"
            )
        )
    return mismatches


def _compare_proc_card(spec: ProcessSpec) -> list[Mismatch]:
    expected = reference_proc_lines(spec)
    actual = [
        _canonical_import(line)
        for line in proc_card_commands(spec, output_dir=Path(spec.name))
        if not line.startswith("output ")
    ]
    if expected == actual:
        return []
    return [Mismatch(spec.name, "proc_card", " | ".join(expected), " | ".join(actual))]


def _compare_madspin(spec: ProcessSpec) -> list[Mismatch]:
    reference_card = _reference_dir(spec) / "madspin_card.dat"
    if reference_card.is_file() != spec.madspin:
        return [
            Mismatch(
                spec.name, "madspin", str(reference_card.is_file()), str(spec.madspin)
            )
        ]
    if not spec.madspin:
        return []
    reference = parse_madspin_card(reference_card.read_text("utf-8"))
    card = parse_madspin_card(madspin_card_text(spec))
    return [
        Mismatch(spec.name, f"madspin {d.item}", d.expected, d.actual)
        for d in compare_madspin_cards(card, reference)
    ]


def _canonical_import(line: str) -> str:
    """Reduce an ``import model`` line to the bare catalogue model name."""
    if not line.startswith("import model "):
        return line
    target = line[len("import model ") :].strip()
    name = Path(target).name if "/" in target else target
    return f"import model {_OFFICIAL_MODEL_ALIASES.get(name, name)}"
