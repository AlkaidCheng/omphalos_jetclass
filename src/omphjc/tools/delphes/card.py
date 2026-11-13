"""Read, compare and adapt Delphes cards.

A Delphes card is a Tcl script. At the top level, ``set`` assigns variables
such as ``ExecutionPath`` or ``RandomSeed``. Each
``module Type Name { ... }`` block assigns the parameters of one module with
``set`` and ``add``. Some blocks assign them in loops that build calorimeter
binnings.

Delphes reads the card with a Tcl interpreter. This module does the same
with the Tcl interpreter that comes with Python, and returns the evaluated
configuration as keys and values. Two cards therefore compare equal when
they differ only in whitespace, comments, loop spelling or the order of
definitions.

The official JetClass card is the CMS card distributed with Delphes, adapted
to jet tagging. The CMS card is ``cards/delphes_card_CMS.tcl`` in Delphes. It
is identical from Delphes 3.4.2 to 3.5.1 and is included here as
``config/references/delphes/delphes_card_CMS.tcl``.

Section 2 of the JetClass paper describes the adaptation
(https://arxiv.org/abs/2202.03772):

- the propagation, tracking, calorimeter and particle-flow modules are the CMS
  ones, unchanged except that ``ECal`` reads the smeared tracks;
- a ``TrackSmearing`` module smears the impact parameters of charged tracks to
  the resolution of the CMS tracker (https://arxiv.org/abs/1405.6569);
- ``FatJetFinder`` and ``GenJetFinder`` cluster anti-kT jets with R = 0.8 and
  pT > 500 GeV, with N-subjettiness and soft-drop observables;
- the modules for isolated leptons and photons, missing energy, flavour tagging
  and R = 0.5 jets are removed, and the output keeps the generator particles,
  the particle-flow candidates and the two jet collections.

The JetClass card is kept under ``config/references/jetclass/`` as the
default reference for comparisons. A run uses the card that the catalogue
names.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any, ClassVar

from omphjc.comparison import Difference
from omphjc.config_paths import delphes_reference_card_path
from omphjc.data_files import Card

ParameterValue = tuple[str, ...]
"""A Delphes parameter as the list of Tcl elements it evaluates to.

A scalar is a one-element tuple. A list built with ``add``, or a braced block
such as a formula, is the tuple of its whitespace-separated elements.
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
class DelphesCard(Card):
    """The evaluated configuration of a Delphes card.

    Parameters
    ----------
    execution_path : tuple[str, ...]
        Module names in execution order.
    modules : Mapping[str, ModuleConfig]
        Every defined module in definition order, whether or not it is
        executed.
    settings : Mapping[str, ParameterValue]
        Top-level variables other than ``ExecutionPath``, for example
        ``RandomSeed`` or ``MaxEvents``.
    """

    format_name: ClassVar[str] = "delphes_card"
    record_version: ClassVar[int] = 1

    execution_path: tuple[str, ...]
    modules: Mapping[str, ModuleConfig]
    settings: Mapping[str, ParameterValue]

    @classmethod
    def from_text(cls, text: str) -> "DelphesCard":
        """Evaluate a card given as Tcl source and return its configuration.

        Raises
        ------
        ValueError
            If the card is not valid Tcl for the Delphes reader.
        ModuleNotFoundError
            If this Python has no ``tkinter``, its interface to Tcl.
        """
        try:
            import tkinter
        except ModuleNotFoundError as error:
            raise ModuleNotFoundError(
                "Reading a Delphes card needs Python's tkinter module, which this "
                "Python lacks; install a Python with Tcl support, as the README's "
                "Installation section describes",
                name="tkinter",
            ) from error

        interpreter = tkinter.Tcl()
        interpreter.eval(_READER_PROCEDURES)
        globals_before = set(interpreter.eval("info globals").split())
        try:
            interpreter.eval(text)
        except tkinter.TclError as error:
            raise ValueError(f"Delphes card does not evaluate: {error}") from error

        def elements(variable: str) -> ParameterValue:
            # tkinter converts numbers and lists to Python objects; joining inside
            # Tcl keeps every element, nested lists included, in its canonical
            # string form.
            joined = str(interpreter.eval(f'join [set {variable}] "\\x1f"'))
            return tuple(joined.split("\x1f")) if joined else ()

        module_names: ParameterValue = ()
        if interpreter.eval(f"info exists ::{_INTERNAL_PREFIX}order") == "1":
            module_names = elements(f"::{_INTERNAL_PREFIX}order")
        modules: dict[str, ModuleConfig] = {}
        for name in module_names:
            parameters = {
                variable.rsplit("::", 1)[1]: elements(variable)
                for variable in sorted(
                    interpreter.eval(f"info vars ::{name}::*").split()
                )
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
        return cls(execution_path=execution_path, modules=modules, settings=settings)

    def content_record(self) -> dict[str, Any]:
        """Return the execution path, the top-level settings and the modules.

        A module is written as its Delphes class and its parameters, and a
        value as the list of its Tcl elements. The order in which a card
        defines its modules and sets its variables does not change the
        fingerprint.
        """
        return {
            "execution_path": list(self.execution_path),
            "settings": {key: list(value) for key, value in self.settings.items()},
            "modules": {
                name: {
                    "type": module.type,
                    "parameters": {
                        key: list(value) for key, value in module.parameters.items()
                    },
                }
                for name, module in self.modules.items()
            },
        }

    def differences(self, reference: "DelphesCard") -> list[Difference]:
        """Return every configuration difference between this card and `reference`.

        The execution path is compared in order. The top-level settings, the
        modules and the parameters of a module are compared by name. A
        top-level setting is named ``settings.<name>``, and a parameter is
        named ``<module>.<parameter>``. A module that only one card defines
        is named ``module``, and its name is the value. Numeric values are
        compared as numbers.
        """
        differences: list[Difference] = []
        if self.execution_path != reference.execution_path:
            differences.append(
                Difference(
                    "ExecutionPath",
                    " ".join(reference.execution_path),
                    " ".join(self.execution_path),
                )
            )
        differences.extend(
            Difference.between_mappings(
                self.settings,
                reference.settings,
                equal=_values_equal,
                text=_abbreviate,
                name="settings.{}".format,
            )
        )
        differences.extend(
            Difference.between_collections(
                sorted(self.modules), sorted(reference.modules), item="module"
            )
        )
        for module_name in sorted(self.modules.keys() & reference.modules.keys()):
            module, expected = self.modules[module_name], reference.modules[module_name]
            if module.type != expected.type:
                differences.append(
                    Difference(f"module {module_name}", expected.type, module.type)
                )
            differences.extend(
                Difference.between_mappings(
                    module.parameters,
                    expected.parameters,
                    equal=_values_equal,
                    text=_abbreviate,
                    name=f"{module_name}.{{}}".format,
                )
            )
        return differences


def reference_card_text() -> str:
    """Return the official JetClass card as text."""
    return delphes_reference_card_path().read_text(encoding="utf-8")


@cache
def reference_card() -> DelphesCard:
    """Return the evaluated configuration of the official JetClass card."""
    return DelphesCard.read(delphes_reference_card_path())


def with_random_seed(text: str, seed: int) -> str:
    """Return `text` with a ``set RandomSeed`` line appended.

    Delphes evaluates a card from top to bottom and uses the last value it sets,
    so the appended seed applies even when `text` sets ``RandomSeed`` itself.
    Without such a line Delphes seeds its random generator from the clock.
    """
    return f"{text}\nset RandomSeed {seed}\n"


_PARTICLES_CARD = """\
# Delphes card that writes the generator record and simulates nothing.
#
# DelphesPythia8 fills the Delphes/allParticles array from every Pythia event
# before the modules in ExecutionPath run. With the TreeWriter as the only
# module, the output holds the Particle branch (every generator particle with
# its status, mothers, daughters, momentum and production vertex) next to the
# Event, Weight, EventLHEF and WeightLHEF branches the program writes itself,
# the last two for an LHE input, and no detector module runs. DelphesROOT
# reads such a file to simulate the detector later.

set ExecutionPath {
  TreeWriter
}

module TreeWriter TreeWriter {
  add Branch Delphes/allParticles Particle GenParticle
}
"""


def particles_card_text() -> str:
    """Return the Delphes card that keeps the generator record and simulates nothing.

    With this card, ``DelphesPythia8`` acts as Pythia's event loop followed by
    a ROOT writer. No detector module is executed. The output holds these
    branches:

    - ``Particle``, the complete generator record of every event;
    - ``Event`` and ``Weight``, which the program writes itself;
    - ``EventLHEF`` and ``WeightLHEF``, which the program also writes itself
      because its input is an LHE file.

    ``DelphesROOT`` reads such a file later to apply a detector card to it.
    """
    return _PARTICLES_CARD


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


def _abbreviate(value: ParameterValue, limit: int = 6) -> str:
    if len(value) <= limit:
        return " ".join(value)
    head = " ".join(value[: limit // 2])
    tail = " ".join(value[-(limit // 2) :])
    return f"{head} … {tail} ({len(value)} elements)"
