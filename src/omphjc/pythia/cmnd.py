"""Pythia 8 settings for showering MadGraph events in ``DelphesPythia8``.

The official production showered through MadGraph's Pythia interface, which
writes a command file from the run card. ``DelphesPythia8`` reads a command
file of its own, so this module writes the equivalent one, in layers where a
later layer overrides an earlier one:

1. for an MLM-matched process, the values MadGraph derives from the run card:
   ``JetMatching:qCut = 1.5 × xqcut``, ``JetMatching:nQmatch = maxjetflavor``
   and ``JetMatching:nJetMax``, the most light jets in any process line
   (``setup_Pythia8RunAndCard`` in ``madgraph/interface/madevent_interface.py``,
   https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.0/madgraph/interface/madevent_interface.py#L4544-L4602),
   then the catalogue's ``pythia_matching`` block;
2. the catalogue's ``pythia`` settings, written for every process (what
   MadGraph's interface injects into every run), with the entry's own;
3. the run controls of one job: the LHE file, the event count and the seed;
4. any overrides given by the caller.

MadGraph's interface also registers bookkeeping keys of its own
(``HEPMCoutput:*``, ``SysCalc:*``, ``LHEFInputs:*``). They are not Pythia
settings and ``DelphesPythia8`` refuses a file that contains them, so they
never appear here; :data:`MADGRAPH_INTERFACE_PREFIXES` names them for
comparisons against a card MadGraph wrote.
"""

import math
from collections.abc import Iterable, Mapping
from pathlib import Path

from omphjc.comparison import Difference
from omphjc.processes.catalogue import ProcessSpec, SettingValue

MATCHING_SCALE_FACTOR = 1.5
"""``JetMatching:qCut`` as a multiple of the run card's ``xqcut``.

MadGraph's rule when the Pythia card leaves ``qCut`` at -1:
``PY8_Card.MadGraphSet('JetMatching:qCut', 1.5*self.run_card['xqcut'])`` in
``setup_Pythia8RunAndCard``,
https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.0/madgraph/interface/madevent_interface.py#L4544
(the same line in MadGraph 3.1.1 gave the official ``qCut = 45`` for
``xqcut = 30``). A ``JetMatching:qCut`` written in the catalogue replaces it.
"""

PYTHIA_SEED_LIMIT = 900_000_000
"""Largest value Pythia accepts for ``Random:seed``.

``<modeopen name="Random:seed" default="-1" max="900000000">`` in Pythia's
settings database, ``share/Pythia8/xmldoc/RandomNumberSeed.xml`` (8.312);
documented at https://pythia.org/latest-manual/RandomNumberSeed.html. Seed 0
draws the seed from the clock.
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


def shower_settings(
    spec: ProcessSpec,
    *,
    lhe_path: Path,
    n_events: int,
    seed: int | None,
    overrides: Mapping[str, SettingValue] | None = None,
) -> dict[str, str]:
    """Return the Pythia settings for showering `spec` with ``DelphesPythia8``.

    Parameters
    ----------
    spec : ProcessSpec
        The process whose events are showered; its ``pythia`` and
        ``pythia_matching`` settings come from the catalogue.
    lhe_path : Path
        Uncompressed LHE file. ``DelphesPythia8`` also reads it as text for
        its ``EventLHEF`` branch, so a gzipped file cannot be used.
    n_events : int
        Upper bound on the number of showered events; the event loop also
        stops at the end of the LHE file.
    seed : int or None
        ``Random:seed`` between 1 and :data:`PYTHIA_SEED_LIMIT`. ``None``
        draws the seed from the clock (Pythia's built-in default is one fixed
        seed).
    overrides : Mapping[str, SettingValue] or None
        Settings applied last, over every other layer.

    Returns
    -------
    dict[str, str]
        One entry per setting, keys matched case-insensitively as Pythia
        reads them, in the order of the layer that first sets them; values as
        Pythia reads them.

    Raises
    ------
    ValueError
        If `n_events` is not positive or `seed` is outside Pythia's range.
    """
    if n_events <= 0:
        raise ValueError(f"n_events must be positive, got {n_events}")
    if seed is not None and not 1 <= seed <= PYTHIA_SEED_LIMIT:
        raise ValueError(f"seed must be between 1 and {PYTHIA_SEED_LIMIT}, got {seed}")
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
    return _merge(layers)


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
    """Return ``JetMatching:nJetMax``: the most light jets any process line produces.

    Only the hard process counts (the part before any decay chain); the
    jet label is ``j`` as MadGraph's ``max_n_matched_jets`` counts it.
    """
    return max(_jet_count(process) for process in spec.processes)


def format_cmnd(settings: Mapping[str, str], *, title: str) -> str:
    """Return `settings` as the text of a Pythia command file."""
    lines = [f"! Pythia 8 settings for DelphesPythia8: {title}", "!"]
    lines.extend(f"{key} = {value}" for key, value in settings.items())
    return "\n".join(lines) + "\n"


def parse_cmnd(text: str) -> dict[str, str]:
    """Return the settings of a Pythia command file.

    Pythia's reading rules apply: a line is a setting when its first
    non-blank character is a letter or digit, the value is the first word
    after ``=``, keys are case-insensitive and the last occurrence of a key
    wins. The spelling of the last occurrence is kept.
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
    return dict(settings.values())


def compare_settings(
    settings: Mapping[str, str],
    reference: Mapping[str, str],
    *,
    ignore: Iterable[str] = (),
) -> list[Difference]:
    """Return every difference between `settings` and `reference`.

    Keys are compared case-insensitively and values as Pythia reads them:
    ``on``/``off``/``true``/``false``/``yes``/``no`` as booleans, numbers as
    numbers, anything else as text. Entries of `ignore` are lower-case keys,
    or key prefixes ending in ``:``, that are left out of the comparison.
    """
    ignored_keys = {item for item in ignore if not item.endswith(":")}
    ignored_prefixes = tuple(item for item in ignore if item.endswith(":"))

    def is_ignored(lowered: str) -> bool:
        return lowered in ignored_keys or lowered.startswith(ignored_prefixes)

    actual = {key.lower(): (key, value) for key, value in settings.items()}
    expected = {key.lower(): (key, value) for key, value in reference.items()}
    differences = []
    for lowered in sorted(actual.keys() | expected.keys()):
        if is_ignored(lowered):
            continue
        if lowered not in expected:
            key, value = actual[lowered]
            differences.append(Difference(key, "absent", value))
        elif lowered not in actual:
            key, value = expected[lowered]
            differences.append(Difference(key, value, "absent"))
        elif not _values_equal(actual[lowered][1], expected[lowered][1]):
            key, value = expected[lowered]
            differences.append(Difference(key, value, actual[lowered][1]))
    return differences


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
