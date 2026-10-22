"""Locate the configuration included with the package.

The repository keeps it in ``config/`` at the top level: the process
catalogue, the files a run reads (models, MadSpin and Delphes cards) and, under
``references/``, the official JetClass cards kept for comparison. The package
reaches the same directory as ``omphjc/config``, so an installed package finds
its copy next to its own modules. Every accessor returns a real filesystem path
that external tools such as MadGraph can use.
"""

import shutil
from importlib.resources import files
from pathlib import Path

_IGNORED_ON_EXPORT = shutil.ignore_patterns("__pycache__", "*.pyc")


def config_root() -> Path:
    """Return the directory holding the package's configuration."""
    return Path(str(files("omphjc") / "config"))


def catalogue_path() -> Path:
    """Return the path of the default process catalogue."""
    return config_root() / "jetclass.yaml"


def delphes_reference_card_path() -> Path:
    """Return the path of the official JetClass Delphes card."""
    return config_root() / "references" / "jetclass" / "delphes_card.tcl"


def export_config(destination: Path) -> Path:
    """Copy the package's configuration to `destination` for editing.

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
