"""The file conventions that carry events from one stage to the next.

A format names how a file is opened and where its particle-level events are,
not which reconstructed collections it carries: DelphesPythia8's record of the
shower and DelphesROOT's output are both ``delphes-root`` files.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class EventFormat(str, Enum):
    """A file convention that carries events from one stage to the next."""

    LHE = "lhe"
    """Les Houches events, plain or compressed with gzip."""

    DELPHES_ROOT = "delphes-root"
    """ROOT tree ``Delphes`` with the branches ``Particle`` and ``Event``."""


@dataclass(frozen=True)
class EventFile:
    """An event file and its format.

    Attributes
    ----------
    path : Path
        The file.
    format : EventFormat
        How the file is opened and where its events are.
    """

    path: Path
    format: EventFormat
