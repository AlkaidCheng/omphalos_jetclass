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
from typing import ClassVar

from omphjc.comparison import Difference
from omphjc.data_files import Card
from omphjc.processes.catalogue import RunCardValue

_CARD_LINE = re.compile(r"^\s*(?P<value>.+?)\s*=\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_SET_LINE = re.compile(
    r"^\s*set\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<value>.+?)\s*$"
)
_INTEGER = re.compile(r"^[+-]?\d+$")


@dataclass(frozen=True)
class RunCard(Card):
    """The settings of a MadGraph run card.

    Parameters
    ----------
    settings : dict[str, RunCardValue]
        The value of each setting by its name. Each value is converted with
        :func:`parse_value`.
    """

    record_scheme: ClassVar[str] = "run-card-v1"

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
