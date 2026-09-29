"""The process catalogue.

Processes are defined as data in a YAML file, ``config/jetclass.yaml`` for the
ten JetClass classes. Each entry records the MadGraph model, the process
definitions, the run-card settings that pin the physics, the MadSpin card when
the heavy resonances are decayed, whether the sample is MLM-matched, the
per-process seed offset and, when official cards exist, the directory holding
them as the reference the entry is checked against. Paths are relative to the
catalogue file, and a model whose directory exists under the catalogue's
models directory is imported from there.
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

_REQUIRED_KEYS = frozenset(
    {"label", "description", "model", "processes", "run_card", "seed_offset"}
)
_OPTIONAL_KEYS = frozenset(
    {"definitions", "matching", "madspin_card", "reference_cards", "pythia"}
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
        Extra multiparticle definitions in MadGraph syntax, without the
        leading ``define``.
    processes : tuple[str, ...]
        Process definitions; the first becomes ``generate`` and the rest
        ``add process``.
    run_card : Mapping[str, RunCardValue]
        Run-card settings applied at launch, common settings included.
    pythia : Mapping[str, SettingValue]
        Pythia settings written for every run of the process: the
        catalogue's common ``pythia`` block with the process's own entries
        merged in.
    pythia_matching : Mapping[str, SettingValue]
        Pythia settings added when the process is MLM-matched.
    matching : bool
        Whether the sample is MLM-matched (``ickkw = 1``).
    seed_offset : int
        Offset added to the job seed so that samples never share a random
        sequence, as in the official production.
    model_path : Path or None
        Directory of the model when it ships with the catalogue; ``None``
        leaves the model to MadGraph.
    madspin_card : Path or None
        MadSpin card decaying the heavy resonances; ``None`` for no MadSpin.
    reference_cards : Path or None
        Directory of the reference (official) MadGraph cards the entry is
        checked against; ``None`` when there is nothing to check against.
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
        YAML file with an optional ``common`` block (``run_card`` and
        ``pythia`` settings shared by every process, ``pythia_matching``
        settings for the matched ones, and ``models_dir``, by default
        ``models``) and a ``processes`` mapping. Paths inside are resolved relative to
        the file's directory.

    Returns
    -------
    Mapping[str, ProcessSpec]
        Specifications in file order, with the common run-card settings
        merged into each process (process values win).

    Raises
    ------
    ValueError
        If an entry lacks a required key, holds an unknown key or a value of
        the wrong type, names a file that does not exist, shares its label
        with another entry, or is matched while the catalogue has no
        ``pythia_matching`` block switching matching on.
    """
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    base = path.parent
    common = document.get("common", {})
    shared = _Shared(
        run_card=_read_run_card(common.get("run_card", {})),
        pythia=_read_settings(common.get("pythia", {})),
        pythia_matching=_read_settings(common.get("pythia_matching", {})),
        models_dir=base / common.get("models_dir", _DEFAULT_MODELS_DIR),
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

    run_card: Mapping[str, RunCardValue]
    pythia: Mapping[str, SettingValue]
    pythia_matching: Mapping[str, SettingValue]
    models_dir: Path


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
    run_card.update(_read_run_card(entry["run_card"]))
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
        definitions=tuple(entry.get("definitions", ())),
        processes=tuple(entry["processes"]),
        run_card=run_card,
        pythia=pythia,
        pythia_matching=dict(shared.pythia_matching),
        matching=matching,
        seed_offset=int(entry["seed_offset"]),
        model_path=model_dir if model_dir.is_dir() else None,
        madspin_card=_existing(name, entry, "madspin_card", base, directory=False),
        reference_cards=_existing(name, entry, "reference_cards", base, directory=True),
    )


def _existing(
    name: str, entry: Mapping[str, Any], key: str, base: Path, *, directory: bool
) -> Path | None:
    if entry.get(key) is None:
        return None
    path = base / str(entry[key])
    if directory and not path.is_dir() or not directory and not path.is_file():
        raise ValueError(f"Process {name!r}: {key} {str(entry[key])!r} does not exist")
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
