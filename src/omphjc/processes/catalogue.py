"""The process catalogue.

Processes are defined as data in a YAML file. The file for the ten JetClass
classes is ``config/jetclass.yaml``. Each entry records:

- the MadGraph model;
- the process definitions;
- the run-card and Pythia settings;
- the MadSpin card, when the heavy resonances are decayed;
- whether the sample is MLM-matched;
- the seed offset;
- optionally, the reference cards that ``omphjc check-cards`` compares the
  entry with.

A ``common`` block holds the settings shared by every entry and names the
Delphes card. Paths are absolute or relative to the catalogue file.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from omphjc.config_paths import catalogue_path
from omphjc.safe_paths import require_plain_name

RunCardValue = bool | int | float | str | dict[int, float]
"""A MadGraph run-card value as it appears after ``set name value``."""

SettingValue = bool | int | float | str
"""A Pythia setting value as written in the catalogue."""

_TOP_LEVEL_KEYS = frozenset({"common", "processes"})
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

# A model's base name becomes a folder name under models_dir, and it may carry
# one restriction suffix after "-"; the process name is screened as a plain
# name, since it becomes a directory name.
_MODEL_NAME = re.compile(r"[A-Za-z0-9_]+(-[A-Za-z0-9_]+)?")


@dataclass(frozen=True)
class ProcessSpec:
    """Everything needed to generate one process.

    Parameters
    ----------
    name : str
        Catalogue name, for example ``"HToBB"``. It must be a plain name
        (:func:`omphjc.safe_paths.require_plain_name`), because it names
        directories.
    label : str
        Class name of the sample, the suffix of the ``label_*`` column.
    description : str
        Human-readable description of the physics.
    model : str
        MadGraph model name, optionally with a ``-restriction`` suffix, for
        example ``"heft-ckm"``. Both parts consist of letters, digits and
        ``_``.
    definitions : tuple[str, ...]
        Multiparticle definitions in MadGraph syntax, without the leading
        ``define``. The common definitions of the catalogue come first and
        the entry's own follow, so an entry can redefine a common name.
    processes : tuple[str, ...]
        Process definitions. The first becomes ``generate`` and each of the
        others becomes ``add process``.
    run_card : Mapping[str, RunCardValue]
        Run-card settings applied at launch. They are the common settings of
        the catalogue with the entry's own settings merged in. Where both
        set a value, the entry's value is used.
    pythia : Mapping[str, SettingValue]
        Pythia settings written for every run of the process. They are the
        common ``pythia`` block of the catalogue with the process's own
        entries merged in.
    pythia_matching : Mapping[str, SettingValue]
        Pythia settings added when the process is MLM-matched.
    matching : bool
        Whether the sample is MLM-matched (``ickkw = 1``).
    seed_offset : int
        Offset added to every job seed of the process. It is 0 unless the
        entry sets one.
    model_dir : Path or None
        Directory of the model when the catalogue includes it. ``None``
        leaves the model to MadGraph.
    madspin_card : Path or None
        MadSpin card that decays the heavy resonances. It is ``None`` when
        MadSpin is not used.
    delphes_card : Path or None
        Delphes card of the detector simulation. The catalogue names it once
        for every process, in its ``common`` block. It is ``None`` when the
        catalogue names no card.
    reference_cards : Path or None
        Directory of the MadGraph cards that ``omphjc check-cards`` compares
        the entry with. It is ``None`` for an entry that is not compared.
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
    model_dir: Path | None
    madspin_card: Path | None
    delphes_card: Path | None
    reference_cards: Path | None

    def __post_init__(self) -> None:
        require_plain_name(self.name, what="Process name")
        if not _MODEL_NAME.fullmatch(self.model):
            raise ValueError(
                f"Process {self.name!r}: model {self.model!r} must be a name of "
                "letters, digits and '_', with at most one '-restriction' suffix"
            )

    @property
    def model_base(self) -> str:
        """Model name without its restriction suffix."""
        return self.model.partition("-")[0]

    @property
    def model_restriction(self) -> str:
        """Restriction suffix of the model, empty when the default applies."""
        return self.model.partition("-")[2]

    @property
    def uses_madspin(self) -> bool:
        """Whether MadSpin decays the heavy resonances."""
        return self.madspin_card is not None


class CatalogueError(ValueError):
    """The content of a catalogue file is not a valid catalogue.

    The message names the file.
    """


def process_names() -> tuple[str, ...]:
    """Return the catalogue names in production order."""
    return tuple(default_catalogue())


def get_process(name: str) -> ProcessSpec:
    """Return the specification of one process.

    Raises
    ------
    KeyError
        If `name` is not in the catalogue; the message lists the valid names.
    """
    try:
        return default_catalogue()[name]
    except KeyError:
        known = ", ".join(process_names())
        raise KeyError(f"Unknown process {name!r}; known processes: {known}") from None


@cache
def default_catalogue() -> Mapping[str, ProcessSpec]:
    """Return the default catalogue, keyed by process name.

    Raises
    ------
    CatalogueError
        If the default catalogue file is not a valid catalogue.
    """
    return read_catalogue(catalogue_path())


def read_catalogue(path: Path) -> Mapping[str, ProcessSpec]:
    """Load a catalogue file.

    Parameters
    ----------
    path : Path
        YAML file with a ``processes`` mapping and an optional ``common``
        block. The ``common`` block may hold:

        - ``definitions``, ``run_card`` and ``pythia`` settings, shared by
          every process;
        - ``pythia_matching`` settings, for the matched processes;
        - the ``delphes_card``;
        - the ``models_dir``, by default ``models``.

        Relative paths in the file are resolved against the directory of the
        file. Absolute paths are used unchanged.

    Returns
    -------
    Mapping[str, ProcessSpec]
        Specifications in file order. The common definitions, run-card
        settings and Pythia settings are merged into each entry, and the
        entry's values take precedence.

    Raises
    ------
    CatalogueError
        If one of the following holds. The message names the file.

        - The file is not UTF-8 YAML that holds a ``processes`` mapping.
        - The ``common`` block, an entry or a settings block is not a
          mapping.
        - ``definitions`` or the ``processes`` of an entry is not a list of
          strings.
        - The ``matching`` of an entry is not a boolean.
        - The file, the ``common`` block or an entry holds an unknown key.
        - An entry lacks a required key.
        - An entry has a malformed process name or model name.
        - An entry holds a value of the wrong type.
        - A named file does not exist.
        - Two entries share a label.
        - An entry is matched while ``common.pythia_matching`` sets no
          ``JetMatching:merge``.
    """
    try:
        with path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
        return _read_document(document, base_dir=path.parent)
    except (yaml.YAMLError, ValueError) as error:
        raise CatalogueError(f"Catalogue {path}: {error}") from error


def _read_document(document: Any, *, base_dir: Path) -> dict[str, ProcessSpec]:
    if not isinstance(document, dict):
        raise ValueError("The file holds no 'processes' mapping")
    unknown = document.keys() - _TOP_LEVEL_KEYS
    if unknown:
        raise ValueError(f"The file has unknown top-level keys: {sorted(unknown)}")
    entries = document.get("processes")
    if not isinstance(entries, dict):
        raise ValueError("The file holds no 'processes' mapping")
    common = document.get("common", {})
    if not isinstance(common, dict):
        raise ValueError(f"The common block must be a mapping, got {common!r}")
    unknown = common.keys() - _COMMON_KEYS
    if unknown:
        raise ValueError(f"The common block has unknown keys: {sorted(unknown)}")
    shared = _Shared(
        definitions=_strings("common", common, "definitions"),
        run_card=_read_run_card(_mapping("common", common, "run_card")),
        pythia=_read_settings(_mapping("common", common, "pythia")),
        pythia_matching=_read_settings(_mapping("common", common, "pythia_matching")),
        models_dir=base_dir / common.get("models_dir", _DEFAULT_MODELS_DIR),
        delphes_card=_existing(
            "common", common, "delphes_card", base_dir, directory=False
        ),
    )
    specs = {
        name: _build_spec(name, entry, shared, base_dir=base_dir)
        for name, entry in entries.items()
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
    name: str, entry: Any, shared: _Shared, *, base_dir: Path
) -> ProcessSpec:
    owner = f"Process {name!r}"
    if not isinstance(entry, dict):
        raise ValueError(f"{owner} must be a mapping, got {entry!r}")
    missing = _REQUIRED_KEYS - entry.keys()
    if missing:
        raise ValueError(f"{owner} lacks required keys: {sorted(missing)}")
    unknown = entry.keys() - _REQUIRED_KEYS - _OPTIONAL_KEYS
    if unknown:
        raise ValueError(f"{owner} has unknown keys: {sorted(unknown)}")
    run_card = dict(shared.run_card)
    run_card.update(_read_run_card(_mapping(owner, entry, "run_card")))
    pythia = dict(shared.pythia)
    pythia.update(_read_settings(_mapping(owner, entry, "pythia")))
    matching = entry.get("matching", False)
    if not isinstance(matching, bool):
        raise ValueError(f"{owner}: matching must be true or false, got {matching!r}")
    if matching and "JetMatching:merge" not in shared.pythia_matching:
        raise ValueError(
            f"{owner} is matched but the catalogue's common.pythia_matching "
            "block does not switch JetMatching:merge on"
        )
    model = str(entry["model"])
    model_dir = shared.models_dir / model.partition("-")[0]
    return ProcessSpec(
        name=name,
        label=str(entry["label"]),
        description=str(entry["description"]),
        model=model,
        definitions=shared.definitions + _strings(owner, entry, "definitions"),
        processes=_strings(owner, entry, "processes"),
        run_card=run_card,
        pythia=pythia,
        pythia_matching=dict(shared.pythia_matching),
        matching=matching,
        seed_offset=int(entry.get("seed_offset", 0)),
        model_dir=model_dir if model_dir.is_dir() else None,
        madspin_card=_existing(owner, entry, "madspin_card", base_dir, directory=False),
        delphes_card=shared.delphes_card,
        reference_cards=_existing(
            owner, entry, "reference_cards", base_dir, directory=True
        ),
    )


def _mapping(owner: str, block: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Return the mapping under `key` of `block`, empty when the key is absent."""
    value = block.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{owner}: {key} must be a mapping, got {value!r}")
    return value


def _strings(owner: str, block: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """Return the list of strings under `key` of `block`, empty when it is absent."""
    value = block.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{owner}: {key} must be a list of strings, got {value!r}")
    return tuple(value)


def _existing(
    owner: str, block: Mapping[str, Any], key: str, base_dir: Path, *, directory: bool
) -> Path | None:
    if block.get(key) is None:
        return None
    path = base_dir / str(block[key])
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
