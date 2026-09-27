"""The JetClass-I process catalogue.

Ten processes are defined as data in ``jetclass.yaml``. Each entry records the
MadGraph model, the process definitions, the run-card settings that pin the
physics, whether MadSpin decays the tops, whether the sample is MLM-matched and
the per-process seed offset. The official gridpack cards packaged under
``resources/jetclass`` are the reference these values are tested against.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

RunCardValue = bool | int | float | str | dict[int, float]
"""A MadGraph run-card value as it appears after ``set name value``."""

_REQUIRED_KEYS = frozenset(
    {"label", "description", "model", "processes", "run_card", "seed_offset"}
)


@dataclass(frozen=True)
class ProcessSpec:
    """Everything needed to generate one JetClass process.

    Parameters
    ----------
    name : str
        Catalogue name, for example ``"HToBB"``.
    label : str
        JetClass class name, the suffix of the ``label_*`` column.
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
    madspin : bool
        Whether the packaged MadSpin card decays the heavy resonances.
    matching : bool
        Whether the sample is MLM-matched (``ickkw = 1``).
    seed_offset : int
        Offset added to the job seed so that samples never share a random
        sequence, as in the official production.
    """

    name: str
    label: str
    description: str
    model: str
    definitions: tuple[str, ...]
    processes: tuple[str, ...]
    run_card: Mapping[str, RunCardValue]
    madspin: bool
    matching: bool
    seed_offset: int

    @property
    def model_base(self) -> str:
        """Model name without its restriction suffix."""
        return self.model.partition("-")[0]

    @property
    def model_restriction(self) -> str:
        """Restriction suffix of the model, empty when the default applies."""
        return self.model.partition("-")[2]


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
    """Return the packaged catalogue, keyed by process name."""
    return load_catalogue(Path(str(files("omphjc.processes") / "jetclass.yaml")))


def load_catalogue(path: Path) -> Mapping[str, ProcessSpec]:
    """Load a catalogue file.

    Parameters
    ----------
    path : Path
        YAML file with a ``common`` block and a ``processes`` mapping.

    Returns
    -------
    Mapping[str, ProcessSpec]
        Specifications in file order, with the common run-card settings
        merged into each process (process values win).

    Raises
    ------
    ValueError
        If an entry lacks a required key or holds a value of the wrong type.
    """
    with path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    common_run_card = _read_run_card(document.get("common", {}).get("run_card", {}))
    specs = {
        name: _build_spec(name, entry, common_run_card)
        for name, entry in document["processes"].items()
    }
    return specs


def _build_spec(
    name: str, entry: Mapping[str, Any], common_run_card: Mapping[str, RunCardValue]
) -> ProcessSpec:
    missing = _REQUIRED_KEYS - entry.keys()
    if missing:
        raise ValueError(f"Process {name!r} lacks required keys: {sorted(missing)}")
    run_card = dict(common_run_card)
    run_card.update(_read_run_card(entry["run_card"]))
    return ProcessSpec(
        name=name,
        label=str(entry["label"]),
        description=str(entry["description"]),
        model=str(entry["model"]),
        definitions=tuple(entry.get("definitions", ())),
        processes=tuple(entry["processes"]),
        run_card=run_card,
        madspin=bool(entry.get("madspin", False)),
        matching=bool(entry.get("matching", False)),
        seed_offset=int(entry["seed_offset"]),
    )


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
