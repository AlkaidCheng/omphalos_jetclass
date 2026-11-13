"""The ROOT file that Delphes writes, and a reader of its generator record.

Delphes writes the generator record to two branches of tree ``Delphes``
(Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/classes/DelphesClasses.h):

- Branch ``Particle`` holds the generator's particles (``GenParticle``).
- Branch ``Event`` holds the event's header (``HepMCEvent``).

DelphesPythia8's record of the shower and DelphesROOT's output both carry
these branches.
"""

from collections.abc import Iterator
from typing import Any, ClassVar

import awkward as ak
import numpy as np

from omphjc.events.formats import EventReader
from omphjc.events.particles import build_record
from omphjc.root_files import ROOTFile
from omphjc.root_io import count_entries, iterate_branches, read_branches

TREE_NAME = "Delphes"

# Delphes writes GenParticle.T in seconds, as position.T() * 1.0E-3 / c_light
# with c_light = 2.99792458E8 m/s (TreeWriter::ProcessParticles,
# https://github.com/delphes/delphes/blob/3.5.1/modules/TreeWriter.cc); the
# record holds c t in mm. The exact SI value of c, in mm/s:
SPEED_OF_LIGHT_MM_PER_S = 2.99792458e11

# Branches go by their bare names, such as Particle.PID, the one name uproot
# finds both in a file ROOT writes, where the full path is Particle/Particle.PID,
# and in one uproot writes, which has no Particle branch above Particle.PID.

# The record's event fields and the branches they come from. Event.ProcessID is
# left out: Pythia gives every Les Houches event the code 9999 (SigmaLHAProcess,
# include/Pythia8/SigmaProcess.h in Pythia 8.312).
EVENT_BRANCHES = {
    "event_number": "Event.Number",
    "weight": "Event.Weight",
    "scale": "Event.Scale",
    "alpha_qcd": "Event.AlphaQCD",
    "alpha_qed": "Event.AlphaQED",
    "id1": "Event.ID1",
    "id2": "Event.ID2",
    "x1": "Event.X1",
    "x2": "Event.X2",
}

# The record's particle fields and the branches they come from.
PARTICLE_BRANCHES = {
    "part_pid": "Particle.PID",
    "part_status": "Particle.Status",
    "part_m1": "Particle.M1",
    "part_m2": "Particle.M2",
    "part_d1": "Particle.D1",
    "part_d2": "Particle.D2",
    "part_charge": "Particle.Charge",
    "part_mass": "Particle.Mass",
    "part_px": "Particle.Px",
    "part_py": "Particle.Py",
    "part_pz": "Particle.Pz",
    "part_e": "Particle.E",
    "part_x": "Particle.X",
    "part_y": "Particle.Y",
    "part_z": "Particle.Z",
    "part_t": "Particle.T",
}

BRANCHES = (*EVENT_BRANCHES.values(), *PARTICLE_BRANCHES.values())


class DelphesROOTFile(ROOTFile):
    """The content of a ROOT file written by Delphes.

    The fields ``ReadTime`` and ``ProcTime`` are left out of the content. They
    hold the time Delphes took to read and to process an event, and that time
    differs between two runs that give the same events.
    """

    format_name: ClassVar[str] = "delphes_root"
    tree_name: ClassVar[str] = TREE_NAME
    # ReadTime and ProcTime are members of Event, the base class of the event
    # header on the branches Event and EventLHEF (Delphes 3.5.1,
    # https://github.com/delphes/delphes/blob/3.5.1/classes/DelphesClasses.h#L46-L55).
    # DelphesPythia8 fills them from its stopwatches
    # (https://github.com/delphes/delphes/blob/3.5.1/readers/DelphesPythia8.cpp#L90-L91
    # and classes/DelphesLHEFReader.cc#L249-L250), and DelphesROOT copies them
    # (readers/DelphesROOT.cpp#L195-L196).
    excluded_fields: ClassVar[frozenset[str]] = frozenset({"ReadTime", "ProcTime"})


class DelphesRootReader(EventReader):
    """Reads the generator record of a Delphes ROOT file.

    The reader refuses a file in these cases:

    - The file has no tree ``Delphes``.
    - The tree lacks one of the branches that the record is read from.
    - The ``Event`` branch does not hold exactly one entry per event.

    A step size given as a memory size counts the uncompressed bytes of the
    branches that are read (:func:`omphjc.root_io.entries_per_step`).
    """

    def count_events(self) -> int:
        return count_entries(self.path, TREE_NAME, BRANCHES)

    def read_particles(
        self,
        *,
        entry_start: int = 0,
        entry_stop: int | None = None,
        downcast: bool = True,
    ) -> ak.Array:
        arrays = read_branches(
            self.path,
            TREE_NAME,
            BRANCHES,
            entry_start=entry_start,
            entry_stop=entry_stop,
        )
        return self._record(arrays, entry_start, downcast=downcast)

    def iterate_particles(
        self, *, step_size: int | str = "100 MB", downcast: bool = True
    ) -> Iterator[ak.Array]:
        for entry_start, arrays in iterate_branches(
            self.path, TREE_NAME, BRANCHES, step_size=step_size
        ):
            yield self._record(arrays, entry_start, downcast=downcast)

    def _record(
        self, arrays: ak.Array, entry_start: int, *, downcast: bool
    ) -> ak.Array:
        """Return the particle record of the branches in `arrays`.

        The first entry of `arrays` is entry `entry_start` of the tree.
        """
        columns: dict[str, Any] = {
            "event_index": np.arange(
                entry_start, entry_start + len(arrays), dtype=np.int64
            )
        }
        # The members of a branch share its entry count, since Delphes writes each
        # branch as one TClonesArray, so one member's count stands for all.
        counts = ak.to_numpy(ak.num(arrays[EVENT_BRANCHES["event_number"]], axis=1))
        offenders = np.flatnonzero(counts != 1)
        if offenders.size:
            first = int(offenders[0])
            raise ValueError(
                f"Event holds {counts[first]} entries at entry {entry_start + first}"
                f" of {self.path}, not one per event"
            )
        for field, branch in EVENT_BRANCHES.items():
            columns[field] = ak.flatten(arrays[branch])
        for field, branch in PARTICLE_BRANCHES.items():
            columns[field] = arrays[branch]
        columns["part_t"] = columns["part_t"] * SPEED_OF_LIGHT_MM_PER_S
        return build_record(columns, downcast=downcast)
