"""Read and write MadGraph run-card values.

A run card stores one setting per line as ``value = name ! comment``; a launch
script overrides settings with ``set name value``. Both forms carry the same
value syntax: booleans as ``True``/``False``, numbers, bare strings, and
PDG-keyed mappings such as ``{25: 450.0}``.
"""

import ast
import math
import re

from omphjc.processes.catalogue import RunCardValue

_CARD_LINE = re.compile(r"^\s*(?P<value>.+?)\s*=\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_SET_LINE = re.compile(
    r"^\s*set\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<value>.+?)\s*$"
)
_INTEGER = re.compile(r"^[+-]?\d+$")


def parse_run_card(text: str) -> dict[str, RunCardValue]:
    """Return the active settings of a run card, keyed by parameter name.

    Comment-only lines and anything after ``#`` or ``!`` are ignored. Values
    keep their run-card spelling apart from the normalisation done by
    :func:`parse_value`.
    """
    settings: dict[str, RunCardValue] = {}
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line)
        match = _CARD_LINE.match(line)
        if match is None:
            continue
        settings[match["name"]] = parse_value(match["value"])
    return settings


def parse_launch_overrides(text: str) -> dict[str, RunCardValue]:
    """Return the ``set name value`` overrides of a launch script, in order."""
    overrides: dict[str, RunCardValue] = {}
    for raw_line in text.splitlines():
        match = _SET_LINE.match(_strip_comment(raw_line))
        if match is None:
            continue
        overrides[match["name"]] = parse_value(match["value"])
    return overrides


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
    """Render a value in the syntax MadGraph accepts after ``set name``."""
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
