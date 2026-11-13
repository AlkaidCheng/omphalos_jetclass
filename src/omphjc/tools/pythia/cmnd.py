"""The Pythia 8 command file for showering MadGraph events in ``DelphesPythia8``.

The official production showered its events through MadGraph's Pythia
interface. That interface writes a command file from the run card.
``DelphesPythia8`` reads a command file of its own, so
:meth:`PythiaCmnd.from_process` writes an equivalent file.

The file is built in four layers of settings. A later layer overrides an
earlier one:

1. For an MLM-matched process, the values that MadGraph derives from the run
   card (``setup_Pythia8RunAndCard`` in
   ``madgraph/interface/madevent_interface.py``,
   https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/interface/madevent_interface.py#L4544-L4602):

   - ``JetMatching:qCut = 1.5 × xqcut``;
   - ``JetMatching:nQmatch = maxjetflavor``;
   - ``JetMatching:nJetMax``, the largest number of light jets in any process
     line.

   The catalogue's ``pythia_matching`` block follows these values.
2. The catalogue's ``pythia`` settings. The settings written for every
   process come first; they are what MadGraph's interface injects into every
   run. The settings of the process's own entry follow.
3. The run controls of one job: the LHE file, the event count and the seed.
4. Any overrides given by the caller.

MadGraph's interface also registers bookkeeping keys of its own
(``HEPMCoutput:*``, ``SysCalc:*``, ``LHEFInputs:*``). These keys are not
Pythia settings, and ``DelphesPythia8`` refuses a file that contains them.
The command file written here therefore never contains them.
:data:`MADGRAPH_INTERFACE_PREFIXES` names them, so that a comparison with a
card that MadGraph wrote can leave them out.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from omphjc.comparison import Difference
from omphjc.data_files import Card
from omphjc.processes.catalogue import ProcessSpec, SettingValue

MATCHING_SCALE_FACTOR = 1.5
"""``JetMatching:qCut`` as a multiple of the run card's ``xqcut``.

MadGraph applies this factor when the Pythia card leaves ``qCut`` at -1. The
rule is the line
``PY8_Card.MadGraphSet('JetMatching:qCut', 1.5*self.run_card['xqcut'])`` in
``setup_Pythia8RunAndCard``
(https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/interface/madevent_interface.py#L4544).

The same line in MadGraph 3.1.1 gave the official ``qCut = 45`` for
``xqcut = 30``. A ``JetMatching:qCut`` written in the catalogue replaces the
derived value.
"""

PYTHIA_SEED_LIMIT = 900_000_000
"""Largest value Pythia accepts for ``Random:seed``.

The limit is the ``max`` attribute of
``<modeopen name="Random:seed" default="-1" max="900000000">`` in Pythia's
settings database, ``share/Pythia8/xmldoc/RandomNumberSeed.xml`` (8.312). The
setting is documented at
https://pythia.org/latest-manual/RandomNumberSeed.html.

With seed 0, Pythia draws the seed from the clock.
"""

MADGRAPH_INTERFACE_PREFIXES: frozenset[str] = frozenset(
    {"hepmcoutput:", "syscalc:", "lhefinputs:"}
)
"""Lower-case prefixes of the keys MadGraph's Pythia interface registers for itself."""

_JET_LABEL = "j"
_BOOLEAN_WORDS = {
    "on": True,
    "off": False,
    "true": True,
    "false": False,
    "yes": True,
    "no": False,
}


@dataclass(frozen=True)
class PythiaCmnd(Card):
    """The settings of a Pythia command file.

    A command file holds one setting on each line, written as ``key = value``.
    Pythia reads a key without regard to its case.

    Parameters
    ----------
    settings : dict[str, str]
        The value of each setting by its key. A key is spelled as the file
        spells it, and no two keys differ only in case. A value is the text
        that Pythia reads.
    """

    format_name: ClassVar[str] = "pythia_cmnd"
    record_version: ClassVar[int] = 1

    settings: dict[str, str]

    @classmethod
    def from_text(cls, text: str) -> "PythiaCmnd":
        """Return the settings of a command file given as text.

        Pythia's reading rules apply. A line is a setting when its first
        character that is not blank is a letter or a digit. The value is the
        first word after ``=``. When several lines give one key, the last
        line counts, and the key keeps the spelling of that line.
        """
        settings: dict[str, tuple[str, str]] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or not line[0].isalnum() or "=" not in line:
                continue
            key, _, rest = line.partition("=")
            words = rest.split()
            if not words:
                continue
            settings[key.strip().lower()] = (key.strip(), words[0])
        return cls(settings=dict(settings.values()))

    @classmethod
    def from_process(
        cls,
        spec: ProcessSpec,
        *,
        lhe_path: Path,
        n_events: int,
        seed: int | None,
        overrides: Mapping[str, SettingValue] | None = None,
    ) -> "PythiaCmnd":
        """Return the command file for showering `spec` with ``DelphesPythia8``.

        Parameters
        ----------
        spec : ProcessSpec
            The process whose events are showered. Its ``pythia`` and
            ``pythia_matching`` settings come from the catalogue.
        lhe_path : Path
            Uncompressed LHE file. ``DelphesPythia8`` also reads it as text
            for its ``EventLHEF`` branch, so a gzipped file cannot be used.
        n_events : int
            Upper bound on the number of showered events. The event loop also
            stops at the end of the LHE file.
        seed : int or None
            The value of ``Random:seed``, between 1 and
            :data:`PYTHIA_SEED_LIMIT`. With ``None``, Pythia draws the seed
            from the clock. Pythia's built-in default is different: it is one
            fixed seed.
        overrides : Mapping[str, SettingValue] or None
            Settings applied last, over every other layer.

        Returns
        -------
        PythiaCmnd
            The settings, ordered by the layer that first sets each of them.
            Each value is written with :func:`format_setting`.

        Raises
        ------
        ValueError
            If `n_events` is not positive or `seed` is outside Pythia's range.
        """
        if n_events <= 0:
            raise ValueError(f"n_events must be positive, got {n_events}")
        if seed is not None and not 1 <= seed <= PYTHIA_SEED_LIMIT:
            raise ValueError(
                f"seed must be between 1 and {PYTHIA_SEED_LIMIT}, got {seed}"
            )
        layers: list[Mapping[str, SettingValue]] = []
        if spec.matching:
            layers.append(_derived_matching_settings(spec))
            layers.append(spec.pythia_matching)
        layers.append(spec.pythia)
        layers.append(
            {
                "Beams:LHEF": str(lhe_path),
                "Main:numberOfEvents": n_events,
                "Random:setSeed": True,
                "Random:seed": 0 if seed is None else seed,
            }
        )
        layers.append(overrides or {})
        return cls(settings=_merge(layers))

    def to_text(self, *, title: str) -> str:
        """Return the settings as the text of a command file.

        `title` ends the comment on the first line of the text.
        """
        lines = [f"! Pythia 8 settings for DelphesPythia8: {title}", "!"]
        lines.extend(f"{key} = {value}" for key, value in self.settings.items())
        return "\n".join(lines) + "\n"

    def content_record(self) -> dict[str, bool | float | str]:
        """Return the settings as Pythia reads them.

        Each key is in lower case. Each value is converted as follows:

        - one of the words ``on``, ``off``, ``true``, ``false``, ``yes`` and
          ``no`` becomes a boolean;
        - a number becomes a number;
        - anything else stays text.
        """
        return {key.lower(): _normalise(value) for key, value in self.settings.items()}

    def differences(
        self, reference: "PythiaCmnd", *, ignore: Iterable[str] = ()
    ) -> list[Difference]:
        """Return one difference for each setting that differs from `reference`.

        Keys are compared without regard to case. Values are compared as
        Pythia reads them: the words for ``on`` and ``off`` are booleans,
        numbers are numbers, and anything else is text.

        The differences are sorted by the key in lower case. Each difference
        names its setting by the key as `reference` spells it. When
        `reference` lacks the setting, the key is spelled as this card spells
        it.

        Parameters
        ----------
        reference : PythiaCmnd
            The command file to compare with.
        ignore : Iterable[str], optional
            Settings left out of the comparison. An entry is a key in lower
            case. An entry that ends in ``:`` is a prefix in lower case, and
            it leaves out every key that starts with it.
        """
        ignored_keys = {entry for entry in ignore if not entry.endswith(":")}
        ignored_prefixes = tuple(entry for entry in ignore if entry.endswith(":"))
        written = {key.lower(): key for key in (*self.settings, *reference.settings)}
        actual, expected = (
            {
                key.lower(): value
                for key, value in card.settings.items()
                if key.lower() not in ignored_keys
                and not key.lower().startswith(ignored_prefixes)
            }
            for card in (self, reference)
        )
        return Difference.between_mappings(
            actual, expected, equal=_values_equal, name=written.__getitem__
        )


def format_setting(value: SettingValue) -> str:
    """Return `value` as Pythia reads it: ``on``/``off`` for booleans."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def matching_scale(spec: ProcessSpec) -> float:
    """Return ``JetMatching:qCut`` for `spec`: ``1.5 × xqcut``.

    Raises
    ------
    ValueError
        If `spec` is not MLM-matched or its run card has no ``xqcut``.
    """
    if not spec.matching:
        raise ValueError(f"Process {spec.name!r} is not MLM-matched")
    return MATCHING_SCALE_FACTOR * _numeric_run_card_value(spec, "xqcut")


def max_matched_jets(spec: ProcessSpec) -> int:
    """Return ``JetMatching:nJetMax``: the most jets any process line asks for.

    A jet is a ``j`` in the final state of a process line. ``j`` is MadGraph's
    multiparticle label for a light parton: a gluon or a light quark, and
    also a b quark where the catalogue's ``definitions`` add it.

    Only the hard process is counted, which is the part of the line before
    any decay chain. For example, ``p p > ve ve~ j j @1`` asks for 2 jets.

    MadGraph computes its own ``max_n_matched_jets`` differently
    (``madgraph/iolibs/export_v4.py``, MadGraph 3.8.1,
    https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/iolibs/export_v4.py#L5907-L5921).
    It takes the smaller of two numbers: the highest QCD order of the
    diagrams, and the largest number of massless coloured final-state partons
    of a process.

    The two results differ when a process line names a parton directly, such
    as ``g`` instead of ``j``.
    """
    return max(_jet_count(process) for process in spec.processes)


def _derived_matching_settings(spec: ProcessSpec) -> dict[str, SettingValue]:
    return {
        "JetMatching:qCut": matching_scale(spec),
        "JetMatching:nJetMax": max_matched_jets(spec),
        "JetMatching:nQmatch": int(_numeric_run_card_value(spec, "maxjetflavor")),
    }


def _merge(layers: Iterable[Mapping[str, SettingValue]]) -> dict[str, str]:
    """Merge settings so that later layers win, matching keys case-insensitively."""
    merged: dict[str, tuple[str, str]] = {}
    for layer in layers:
        for key, value in layer.items():
            merged[key.lower()] = (key, format_setting(value))
    return dict(merged.values())


def _values_equal(left: str, right: str) -> bool:
    left_value, right_value = _normalise(left), _normalise(right)
    if isinstance(left_value, bool) or isinstance(right_value, bool):
        return left_value is right_value
    if isinstance(left_value, float) and isinstance(right_value, float):
        return math.isclose(left_value, right_value, rel_tol=1e-9, abs_tol=0.0)
    return left_value == right_value


def _normalise(value: str) -> bool | float | str:
    lowered = value.lower()
    if lowered in _BOOLEAN_WORDS:
        return _BOOLEAN_WORDS[lowered]
    try:
        return float(value)
    except ValueError:
        return value


def _numeric_run_card_value(spec: ProcessSpec, name: str) -> float:
    """Return the run-card value `name` of `spec`, which must be set and numeric."""
    try:
        value = spec.run_card[name]
    except KeyError:
        raise ValueError(
            f"Process {spec.name!r} has no run-card setting {name!r}"
        ) from None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Run-card setting {name!r} of {spec.name!r} is not a number")
    return float(value)


def _jet_count(process: str) -> int:
    hard_process = process.partition(",")[0].partition("@")[0]
    final_state = hard_process.partition(">")[2]
    return sum(token == _JET_LABEL for token in final_state.split())
