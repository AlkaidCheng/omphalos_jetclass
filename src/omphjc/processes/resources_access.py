"""Locate the reference cards, UFO models and Delphes card shipped in the package.

The resources live under ``omphjc/processes/resources`` and are installed as
plain files, so every accessor returns a real filesystem path that external
tools such as MadGraph can be pointed at directly.
"""

from importlib.resources import files
from pathlib import Path

VENDORED_MODELS: frozenset[str] = frozenset({"heft", "heft_c_mass_jetclass"})
"""UFO models shipped with the package; every other model name is left to MadGraph."""


def resource_root() -> Path:
    """Return the directory holding the packaged resources."""
    return Path(str(files("omphjc.processes") / "resources"))


def reference_dir(process: str) -> Path:
    """Return the directory of the official gridpack cards for `process`.

    Parameters
    ----------
    process : str
        Catalogue name, for example ``"HToBB"``.

    Raises
    ------
    FileNotFoundError
        If no reference cards are packaged for `process`.
    """
    directory = resource_root() / "jetclass" / process
    if not directory.is_dir():
        raise FileNotFoundError(f"No reference cards packaged for process {process!r}")
    return directory


def models_dir() -> Path:
    """Return the directory that holds the vendored UFO models."""
    return resource_root() / "models"


def delphes_card_path() -> Path:
    """Return the path of the official JetClass Delphes card."""
    return resource_root() / "delphes" / "delphes_card_JetClass.tcl"
