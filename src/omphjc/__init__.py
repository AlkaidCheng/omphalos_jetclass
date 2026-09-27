"""JetClass sample generation for Delphes and Parnassus."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("omphjc")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0"

__all__ = ["__version__"]
