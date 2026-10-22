"""The process catalogue.

Processes are defined as data in a YAML file, ``config/jetclass.yaml`` for the
ten JetClass classes. Each entry records the MadGraph model, the process
definitions, the run-card and Pythia settings, the MadSpin card when the heavy
resonances are decayed, whether the sample is MLM-matched, the seed offset and,
optionally, the reference cards ``omphjc check-cards`` compares it with. A
``common`` block holds the settings shared by every entry and names the Delphes
card. Paths are absolute or relative to the catalogue file.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from omphjc.config_paths import catalogue_path

RunCardValue = bool | int | float | str | dict[int, float]
"""A MadGraph run-card value as it appears after ``set name value``."""

SettingValue = bool | int | float | str
"""A Pythia setting value as written in the catalogue."""

_REQUIRED_KEYS = frozenset({"label", "description", "model", "processes"})
_OPTIONAL_KEYS = frozenset(
    {
        "definitions",
        "matching",
        "madspin_card",
        "reference_cards",
        "pythia",
        "run_card",
        "seed_offset",
    }
)
_COMMON_KEYS = frozenset(
    {
        "definitions",
        "run_card",
        "pythia",
        "pythia_matching",
        "models_dir",
        "delphes_card",
    }
)
_DEFAULT_MODELS_DIR = "models"


@dataclass(frozen=True)
class ProcessSpec:
    """Everything needed to generate one process.

    Parameters
    ----------
    name : str
        Catalogue name, for example ``"HToBB"``.
    label : str
        Class name of the sample, the suffix of the ``label_*`` column.
    description : str
        Human-readable description of the physics.
    model : str
        MadGraph model name, optionally with a ``-restriction`` suffix, for
        example ``"heft-ckm"``.
    definitions : tuple[str, ...]
        Multiparticle definitions in MadGraph syntax, without the leading
        ``define``: the catalogue's common definitions followed by the entry's
        own, so that an entry can redefine a common name.
    processes : tuple[str, ...]
        Process definitions; the first becomes ``generate`` and the rest
        ``add process``.
    run_card : Mapping[str, RunCardValue]
        Run-card settings applied at launch: the catalogue's common settings
        with the entry's own merged in (the entry wins).
    pythia : Mapping[str, SettingValue]
        Pythia settings written for every run of the process: the
        catalogue's common ``pythia`` block with the process's own entries
        merged in.
    pythia_matching : Mapping[str, SettingValue]
        Pythia settings added when the process is MLM-matched.
    matching : bool
        Whether the sample is MLM-matched (``ickkw = 1``).
    seed_offset : int
        Offset added to every job seed of the process; 0 unless the entry
        sets one.
    model_path : Path or None
        Directory of the model when it ships with the catalogue; ``None``
        leaves the model to MadGraph.
    madspin_card : Path or None
        MadSpin card decaying the heavy resonances; ``None`` for no MadSpin.
    delphes_card : Path or None
        Delphes card of the detector simulation, named once for the whole
        catalogue in its ``common`` block; ``None`` when the catalogue names
        none.
    reference_cards : Path or None
        Directory of the MadGraph cards ``omphjc check-cards`` compares the
        entry with; ``None`` for an entry that is not compared.
    """

    name: str
    label: str
    description: str
    model: str
    definitions: tuple[str, ...]
    processes: tuple[str, ...]
    run_card: Mapping[str, RunCardValue]
    pythia: Mapping[str, SettingValue]
    pythia_matching: Mapping[str, SettingValue]
    matching: bool
    seed_offset: int
    model_path: Path | None
    madspin_card: Path | None
    delphes_card: Path | None
    reference_cards: Path | None

    @property
    def model_base(self) -> str:
        """Model name without its restriction suffix."""
        return self.model.partition("-")[0]

    @property
    def model_restriction(self) -> str:
        """Restriction suffix of the model, empty when the default applies."""
        return self.model.partition("-")[2]

    @property
    def madspin(self) -> bool:
        """Whether MadSpin decays the heavy resonances."""
        return self.madspin_card is not None


def process_names() -> tuple[str, ...]:
    """Return the catalogue names in production order."""
    return tuple(catalogue())


def get_process(name: str) -> ProcessSpec:
    """Return the specification of one process.

    Raises
    ------
    KeyError
        If `name` is not in the catalogue; the message lists the valid names.
    """
    try:
        return catalogue()[name]
    except KeyError:
        known = ", ".join(process_names())
        raise KeyError(f"Unknown process {name!r}; known processes: {known}") from None


@cache
def catalogue() -> Mapping[str, ProcessSpec]:
    """Return the shipped catalogue, keyed by process name."""
    return load_catalogue(catalogue_path())


def load_catalogue(path: Path) -> Mapping[str, ProcessSpec]:
    """Load a catalogue file.

    Parameters
    ----------
    path : Path
        YAML file with an optional ``common`` block (``definitions``,
        ``run_card`` and ``pythia`` settings shared by every process,
        ``pythia_matching`` settings for the matched ones, the
        ``delphes_card`` and the ``models_dir``, by default ``models``) and a
        ``processes`` mapping. Relative paths inside are resolved against the
        file's directory; absolute paths are used as they are.

    Returns
    -------
    Mapping[str, ProcessSpec]
        Specifications in file order, with the common definitions, run-card
        and Pythia settings merged into each entry (the entry's values win).

    Raises
    ------
    ValueError
        If the ``common`` block or an entry holds an unknown key, an entry
        lacks a required key or holds a value of the wrong type, a named file
        does not exist, two entries share a label, or an entry is matched
        while ``common.pythia_matching`` sets no ``JetMatching:merge``.
    """
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    base = path.parent
    common = document.get("common", {})
    unknown = common.keys() - _COMMON_KEYS
    if unknown:
        raise ValueError(f"The common block has unknown keys: {sorted(unknown)}")
    shared = _Shared(
        definitions=tuple(common.get("definitions", ())),
        run_card=_read_run_card(common.get("run_card", {})),
        pythia=_read_settings(common.get("pythia", {})),
        pythia_matching=_read_settings(common.get("pythia_matching", {})),
        models_dir=base / common.get("models_dir", _DEFAULT_MODELS_DIR),
        delphes_card=_existing("common", common, "delphes_card", base, directory=False),
    )
    specs = {
        name: _build_spec(name, entry, shared, base=base)
        for name, entry in document["processes"].items()
    }
    labels = [spec.label for spec in specs.values()]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"Class labels used by more than one process: {duplicates}")
    return specs


@dataclass(frozen=True)
class _Shared:
    """The ``common`` block of a catalogue, resolved."""

    definitions: tuple[str, ...]
    run_card: Mapping[str, RunCardValue]
    pythia: Mapping[str, SettingValue]
    pythia_matching: Mapping[str, SettingValue]
    models_dir: Path
    delphes_card: Path | None


def _build_spec(
    name: str, entry: Mapping[str, Any], shared: _Shared, *, base: Path
) -> ProcessSpec:
    missing = _REQUIRED_KEYS - entry.keys()
    if missing:
        raise ValueError(f"Process {name!r} lacks required keys: {sorted(missing)}")
    unknown = entry.keys() - _REQUIRED_KEYS - _OPTIONAL_KEYS
    if unknown:
        raise ValueError(f"Process {name!r} has unknown keys: {sorted(unknown)}")
    run_card = dict(shared.run_card)
    run_card.update(_read_run_card(entry.get("run_card", {})))
    pythia = dict(shared.pythia)
    pythia.update(_read_settings(entry.get("pythia", {})))
    matching = bool(entry.get("matching", False))
    if matching and "JetMatching:merge" not in shared.pythia_matching:
        raise ValueError(
            f"Process {name!r} is matched but the catalogue's common.pythia_matching "
            "block does not switch JetMatching:merge on"
        )
    model = str(entry["model"])
    model_dir = shared.models_dir / model.partition("-")[0]
    return ProcessSpec(
        name=name,
        label=str(entry["label"]),
        description=str(entry["description"]),
        model=model,
        definitions=shared.definitions + tuple(entry.get("definitions", ())),
        processes=tuple(entry["processes"]),
        run_card=run_card,
        pythia=pythia,
        pythia_matching=dict(shared.pythia_matching),
        matching=matching,
        seed_offset=int(entry.get("seed_offset", 0)),
        model_path=model_dir if model_dir.is_dir() else None,
        madspin_card=_existing(
            f"Process {name!r}", entry, "madspin_card", base, directory=False
        ),
        delphes_card=shared.delphes_card,
        reference_cards=_existing(
            f"Process {name!r}", entry, "reference_cards", base, directory=True
        ),
    )


def _existing(
    owner: str, block: Mapping[str, Any], key: str, base: Path, *, directory: bool
) -> Path | None:
    if block.get(key) is None:
        return None
    path = base / str(block[key])
    if directory and not path.is_dir() or not directory and not path.is_file():
        raise ValueError(f"{owner}: {key} {str(block[key])!r} does not exist")
    return path


def _read_settings(raw: Mapping[str, Any]) -> dict[str, SettingValue]:
    """Validate raw YAML Pythia settings."""
    settings: dict[str, SettingValue] = {}
    for key, value in raw.items():
        if not isinstance(value, bool | int | float | str):
            raise ValueError(f"Unsupported Pythia setting value for {key!r}: {value!r}")
        settings[str(key)] = value
    return settings


def _read_run_card(raw: Mapping[str, Any]) -> dict[str, RunCardValue]:
    """Validate raw YAML run-card values and normalise PDG-keyed mappings."""
    settings: dict[str, RunCardValue] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            settings[key] = {int(pdg): float(cut) for pdg, cut in value.items()}
        elif isinstance(value, bool | int | float | str):
            settings[key] = value
        else:
            raise ValueError(f"Unsupported run-card value for {key!r}: {value!r}")
    return settings
