"""Locate the configuration shipped with the package.

The repository keeps it in ``config/`` at the top level: the process catalogue,
the official JetClass cards that serve as references, the vendored UFO models
and the Delphes card. The package reaches the same directory as ``omphjc/config``,
so an installed package finds its copy next to its own modules. Every accessor
returns a real filesystem path that external tools such as MadGraph can use.
"""

import shutil
from importlib.resources import files
from pathlib import Path

VENDORED_MODELS: frozenset[str] = frozenset({"heft", "heft_c_mass_jetclass"})
"""UFO models shipped in ``config/models``; other model names are left to MadGraph."""

_IGNORED_ON_EXPORT = shutil.ignore_patterns("__pycache__", "*.pyc")


def config_root() -> Path:
    """Return the directory holding the shipped configuration."""
    return Path(str(files("omphjc") / "config"))


def catalogue_path() -> Path:
    """Return the path of the shipped process catalogue."""
    return config_root() / "jetclass.yaml"


def reference_dir(process: str) -> Path:
    """Return the directory of the official gridpack cards for `process`.

    Parameters
    ----------
    process : str
        Catalogue name, for example ``"HToBB"``.

    Raises
    ------
    FileNotFoundError
        If no reference cards are shipped for `process`.
    """
    directory = config_root() / "cards" / "jetclass" / process
    if not directory.is_dir():
        raise FileNotFoundError(f"No reference cards shipped for process {process!r}")
    return directory


def models_dir() -> Path:
    """Return the directory that holds the vendored UFO models."""
    return config_root() / "models"


def delphes_reference_card_path() -> Path:
    """Return the path of the official JetClass Delphes card."""
    return config_root() / "cards" / "delphes" / "delphes_card_JetClass.tcl"


def export_config(destination: Path) -> Path:
    """Copy the shipped configuration to `destination` for editing.

    Parameters
    ----------
    destination : Path
        Directory to create. It must not exist yet.

    Returns
    -------
    Path
        The created directory.

    Raises
    ------
    FileExistsError
        If `destination` already exists.
    """
    if destination.exists():
        raise FileExistsError(f"{destination} already exists")
    shutil.copytree(config_root(), destination, ignore=_IGNORED_ON_EXPORT)
    return destination
