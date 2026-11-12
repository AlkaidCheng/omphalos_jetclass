"""The run card of MadGraph.

A run card holds one setting on each line, written as ``value = name``, with a
comment after ``!`` or ``#``. A launch script changes a setting with the
command ``set name value``. Both forms write a value in the same way: ``True``
or ``False``, a number, a word, or a mapping from PDG codes to cuts such as
``{25: 450.0}``.
"""

import ast
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from omphjc.comparison import Difference
from omphjc.processes.catalogue import ProcessSpec, RunCardValue
from omphjc.tools.madgraph.referenced_card import ReferencedCard

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
"""Run-card parameters that carry physics and are compared with the reference cards.

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

# The run card among the official cards of a process, and the pattern of the
# names of its launch scripts.
_REFERENCE_FILE_NAME = "run_card.dat"
_REFERENCE_LAUNCH_SCRIPT_GLOB = "run_*.mg5"

_CARD_LINE = re.compile(r"^\s*(?P<value>.+?)\s*=\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_SET_LINE = re.compile(
    r"^\s*set\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<value>.+?)\s*$"
)
_INTEGER = re.compile(r"^[+-]?\d+$")


@dataclass(frozen=True)
class RunCard(ReferencedCard):
    """The settings of a MadGraph run card.

    Parameters
    ----------
    settings : dict[str, RunCardValue]
        The value of each setting by its name. Each value is converted with
        :func:`parse_value`.
    """

    format_name: ClassVar[str] = "run_card"
    record_version: ClassVar[int] = 1

    settings: dict[str, RunCardValue]

    @classmethod
    def from_text(cls, text: str) -> "RunCard":
        """Return the settings of a run card given as text."""
        settings = {}
        for line in text.splitlines():
            match = _CARD_LINE.match(_strip_comment(line))
            if match is not None:
                settings[match["name"]] = parse_value(match["value"])
        return cls(settings=settings)

    @classmethod
    def from_process(cls, spec: ProcessSpec) -> "RunCard":
        """Return the settings that the catalogue gives the run card of `spec`."""
        return cls(settings=dict(spec.run_card))

    @classmethod
    def reference(cls, reference_dir: Path) -> "RunCard":
        """Return the official run card as its launch scripts leave it.

        The launch scripts are the ``run_*.mg5`` files of `reference_dir`.
        Their ``set`` commands change settings of the run card.
        """
        card = cls.read(reference_dir / _REFERENCE_FILE_NAME)
        for launcher_path in sorted(reference_dir.glob(_REFERENCE_LAUNCH_SCRIPT_GLOB)):
            card = card.with_set_commands(launcher_path.read_text("utf-8"))
        return card

    def with_set_commands(self, text: str) -> "RunCard":
        """Return the card after the ``set name value`` commands in `text`.

        `text` is a launch script. A command gives its setting a new value,
        and it adds a setting that the card does not hold. When several
        commands name one setting, the last one counts.
        """
        settings = dict(self.settings)
        for line in text.splitlines():
            match = _SET_LINE.match(_strip_comment(line))
            if match is not None:
                settings[match["name"]] = parse_value(match["value"])
        return RunCard(settings=settings)

    def content_record(self) -> dict[str, RunCardValue]:
        """Return the settings."""
        return self.settings

    def differences(self, reference: "RunCard") -> list[Difference]:
        """Return one difference for each setting with another value.

        The differences come in the order of the setting names. A setting
        that one card lacks has the value ``None`` there.
        Values are compared with :func:`values_equal` and written with
        :func:`format_value`.
        """
        return Difference.between_mappings(
            self.settings, reference.settings, equal=values_equal, text=format_value
        )

    def checked_differences(self, reference: "RunCard") -> list[Difference]:
        """Return the differences from `reference` that a check reports.

        The catalogue lists only the settings that carry physics. A setting
        that only `reference` holds is therefore reported when it is one of
        :data:`TRACKED_PARAMETERS` and `reference` does not leave it at its
        value in :data:`DISABLED_DEFAULTS`.
        """
        differences = []
        for difference in self.differences(reference):
            name = difference.item
            if difference.actual is None:
                if name not in TRACKED_PARAMETERS:
                    continue
                if name in DISABLED_DEFAULTS and values_equal(
                    reference.settings[name], DISABLED_DEFAULTS[name]
                ):
                    continue
            differences.append(difference)
        return differences


def parse_value(text: str) -> RunCardValue:
    """Convert one run-card value from its text form.

    Parameters
    ----------
    text : str
        The value as written in a run card or launch script.

    Returns
    -------
    RunCardValue
        ``True``/``False`` become booleans, integers and floats become
        numbers, ``{pdg: cut}`` mappings become ``dict[int, float]`` and
        everything else is returned as a stripped string.

    Raises
    ------
    ValueError
        If `text` starts with ``{`` but is not a valid mapping.
    """
    value = text.strip()
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value.startswith("{"):
        mapping = _parse_pdg_mapping(value)
        return value if mapping is None else mapping
    if _INTEGER.match(value):
        return int(value)
    try:
        number = float(value)
    except ValueError:
        return value
    return number if math.isfinite(number) else value


def format_value(value: RunCardValue) -> str:
    """Format a value in the syntax MadGraph accepts after ``set name``."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, dict):
        entries = ", ".join(f"{pdg}: {cut}" for pdg, cut in sorted(value.items()))
        return f"{{{entries}}}"
    return str(value)


def values_equal(left: RunCardValue, right: RunCardValue) -> bool:
    """Compare two run-card values, treating ``450`` and ``450.0`` as equal.

    Booleans only equal booleans, so ``True`` never matches ``1``.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, dict) or isinstance(right, dict):
        return left == right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return math.isclose(left, right, rel_tol=1e-12, abs_tol=0.0)
    return left == right


def _strip_comment(line: str) -> str:
    for marker in ("#", "!"):
        index = line.find(marker)
        if index >= 0:
            line = line[:index]
    return line


def _parse_pdg_mapping(text: str) -> dict[int, float] | None:
    """Parse a ``{pdg: cut}`` mapping; ``None`` when the keys are not PDG codes.

    Run cards written by MadGraph may spell the PDG keys as strings. Mappings
    with other keys, such as ``{'default': False}``, are not PDG cuts and are
    left to the caller as text.
    """
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"Malformed PDG mapping: {text!r}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"Malformed PDG mapping: {text!r}")
    if not all(_INTEGER.match(str(pdg)) for pdg in parsed):
        return None
    return {int(pdg): float(cut) for pdg, cut in parsed.items()}
