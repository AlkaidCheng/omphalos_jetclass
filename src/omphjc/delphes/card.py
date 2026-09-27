"""Read, compare and adapt Delphes cards.

A Delphes card is a Tcl script: ``set`` assigns top-level variables such as
``ExecutionPath`` or ``RandomSeed``, and each ``module Type Name { ... }`` block
assigns the module's parameters with ``set`` and ``add``, sometimes through
loops that build calorimeter binnings. Delphes reads the card with a Tcl
interpreter, so this module does the same, through the Tcl interpreter that
ships with Python, and exposes the evaluated configuration as keys and values.
Two cards that differ only in whitespace, comments, loop spelling or the order
of definitions therefore compare equal.

The official JetClass card is packaged as a reference to compare against; the
card used for a run may be any file.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from omphjc.processes.resources_access import delphes_card_path

OFFICIAL_CARD_SHA256 = (
    "bf205dd95fe9fe0031847d76edf70a6a8e125ed65141ea9c479aef453588ed1c"
)
"""SHA-256 of ``delphes_card.tcl`` in jet-universe/jetclass_generation @ ae722ea.

Informational: the packaged reference is checked against it, cards used for
runs are compared by configuration, never by hash.
"""

ParameterValue = tuple[str, ...]
"""A Delphes parameter as the list of Tcl elements it evaluates to.

Scalars are one-element tuples; lists built with ``add`` and braced blocks such
as formulas are their whitespace-separated elements.
"""

_READER_PROCEDURES = r"""
proc module {type name body} {
    set ::__omphjc_types($name) $type
    lappend ::__omphjc_order $name
    namespace eval ::$name $body
}
proc add {name args} {
    upvar 1 $name variable
    foreach element $args { lappend variable $element }
}
"""
"""Tcl commands Delphes provides on top of the language when reading a card."""

_INTERNAL_PREFIX = "__omphjc_"


@dataclass(frozen=True)
class ModuleConfig:
    """One ``module`` block: its Delphes class and its parameters."""

    type: str
    parameters: Mapping[str, ParameterValue]


@dataclass(frozen=True)
class DelphesCard:
    """The evaluated configuration of a Delphes card.

    Parameters
    ----------
    execution_path : tuple[str, ...]
        Module names in execution order.
    modules : Mapping[str, ModuleConfig]
        Every defined module, in definition order, executed or not.
    settings : Mapping[str, ParameterValue]
        Top-level variables other than ``ExecutionPath``, for example
        ``RandomSeed`` or ``MaxEvents``.
    """

    execution_path: tuple[str, ...]
    modules: Mapping[str, ModuleConfig]
    settings: Mapping[str, ParameterValue]


@dataclass(frozen=True)
class CardDifference:
    """One configuration difference between a card and a reference."""

    item: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return f"{self.item}: expected {self.expected}, got {self.actual}"


def parse_card(text: str) -> DelphesCard:
    """Evaluate a Delphes card and return its configuration.

    Parameters
    ----------
    text : str
        The card as Tcl source.

    Raises
    ------
    ValueError
        If the card is not valid Tcl for the Delphes reader.
    """
    import tkinter

    interpreter = tkinter.Tcl()
    interpreter.eval(_READER_PROCEDURES)
    globals_before = set(interpreter.eval("info globals").split())
    try:
        interpreter.eval(text)
    except tkinter.TclError as error:
        raise ValueError(f"Delphes card does not evaluate: {error}") from error

    def elements(variable: str) -> ParameterValue:
        # Join in Tcl so every element, nested lists included, comes back in
        # Tcl's canonical string form rather than as a converted Python object.
        joined = str(interpreter.eval(f'join [set {variable}] "\\x1f"'))
        return tuple(joined.split("\x1f")) if joined else ()

    module_names: ParameterValue = ()
    if interpreter.eval(f"info exists ::{_INTERNAL_PREFIX}order") == "1":
        module_names = elements(f"::{_INTERNAL_PREFIX}order")
    modules: dict[str, ModuleConfig] = {}
    for name in module_names:
        parameters = {
            variable.rsplit("::", 1)[1]: elements(variable)
            for variable in sorted(interpreter.eval(f"info vars ::{name}::*").split())
        }
        module_type = str(interpreter.getvar(f"::{_INTERNAL_PREFIX}types({name})"))
        modules[name] = ModuleConfig(type=module_type, parameters=parameters)

    new_globals = set(interpreter.eval("info globals").split()) - globals_before
    settings = {
        variable: elements(f"::{variable}")
        for variable in sorted(new_globals)
        if not variable.startswith(_INTERNAL_PREFIX) and variable != "ExecutionPath"
    }
    execution_path: ParameterValue = ()
    if "ExecutionPath" in new_globals:
        execution_path = elements("::ExecutionPath")
    return DelphesCard(
        execution_path=execution_path, modules=modules, settings=settings
    )


def load_card(path: Path) -> DelphesCard:
    """Read and evaluate the Delphes card at `path`."""
    return parse_card(path.read_text(encoding="utf-8"))


def official_card_text() -> str:
    """Return the packaged official JetClass card as text."""
    return delphes_card_path().read_text(encoding="utf-8")


@cache
def official_card() -> DelphesCard:
    """Return the evaluated configuration of the official JetClass card."""
    return parse_card(official_card_text())


def with_random_seed(text: str, seed: int) -> str:
    """Return `text` with a ``set RandomSeed`` line prepended.

    Without such a line Delphes seeds its random generator from the clock,
    as the official production did.
    """
    return f"set RandomSeed {seed}\n\n{text}"


def compare_cards(card: DelphesCard, reference: DelphesCard) -> list[CardDifference]:
    """Return every configuration difference between `card` and `reference`.

    The execution path is compared in order; modules and their parameters are
    compared by name; numeric values are compared as numbers.
    """
    differences: list[CardDifference] = []
    if card.execution_path != reference.execution_path:
        differences.append(
            CardDifference(
                "ExecutionPath",
                " ".join(reference.execution_path),
                " ".join(card.execution_path),
            )
        )
    differences.extend(_compare_values("settings", card.settings, reference.settings))
    for name in sorted(reference.modules.keys() - card.modules.keys()):
        differences.append(CardDifference(f"module {name}", "defined", "absent"))
    for name in sorted(card.modules.keys() - reference.modules.keys()):
        differences.append(CardDifference(f"module {name}", "absent", "defined"))
    for name in sorted(card.modules.keys() & reference.modules.keys()):
        module, expected = card.modules[name], reference.modules[name]
        if module.type != expected.type:
            differences.append(
                CardDifference(f"module {name}", expected.type, module.type)
            )
        differences.extend(
            _compare_values(name, module.parameters, expected.parameters)
        )
    return differences


def _compare_values(
    scope: str,
    actual: Mapping[str, ParameterValue],
    expected: Mapping[str, ParameterValue],
) -> list[CardDifference]:
    differences = []
    for key in sorted(actual.keys() | expected.keys()):
        if key not in expected:
            differences.append(
                CardDifference(f"{scope}.{key}", "absent", _render(actual[key]))
            )
        elif key not in actual:
            differences.append(
                CardDifference(f"{scope}.{key}", _render(expected[key]), "absent")
            )
        elif not _values_equal(actual[key], expected[key]):
            differences.append(
                CardDifference(
                    f"{scope}.{key}", _render(expected[key]), _render(actual[key])
                )
            )
    return differences


def _values_equal(left: ParameterValue, right: ParameterValue) -> bool:
    if len(left) != len(right):
        return False
    return all(_elements_equal(a, b) for a, b in zip(left, right, strict=True))


def _elements_equal(left: str, right: str) -> bool:
    if left == right:
        return True
    try:
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=0.0)
    except ValueError:
        return False


def _render(value: ParameterValue, limit: int = 6) -> str:
    if len(value) <= limit:
        return " ".join(value)
    head = " ".join(value[: limit // 2])
    tail = " ".join(value[-(limit // 2) :])
    return f"{head} … {tail} ({len(value)} elements)"
