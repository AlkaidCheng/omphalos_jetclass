"""Reader of the generator record in a Delphes ROOT file.

Delphes writes the generator's particles to branch ``Particle``
(``GenParticle``) and the event's header to branch ``Event`` (``HepMCEvent``)
of tree ``Delphes``. DelphesPythia8's record of the shower and DelphesROOT's
output both carry them (Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/classes/DelphesClasses.h).
"""

from collections.abc import Iterator
from typing import Any

import awkward as ak
import numpy as np

from omphjc.events.formats import EventReader
from omphjc.events.particles import build_record
from omphjc.root_io import count_entries, iterate_branches, read_branches

TREE_NAME = "Delphes"

# Delphes writes GenParticle.T in seconds, as position.T() * 1.0E-3 / c_light
# with c_light = 2.99792458E8 m/s (TreeWriter::ProcessParticles,
# https://github.com/delphes/delphes/blob/3.5.1/modules/TreeWriter.cc); the
# record holds c t in mm. The exact SI value of c, in mm/s:
SPEED_OF_LIGHT_MM_PER_S = 2.99792458e11

# Branches are named without their parent, such as Particle.PID, the one name
# uproot finds both in a file ROOT writes and in one uproot writes.

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


class DelphesRootReader(EventReader):
    """Reads the generator record of a Delphes ROOT file.

    The reader refuses a file without tree ``Delphes`` or one of the branches
    the record is read from, and an ``Event`` branch with other than one entry
    per event. A memory step size counts the uncompressed bytes of the branches
    read (:func:`omphjc.root_io.entries_per_step`).
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

    @staticmethod
    def _record(arrays: ak.Array, entry_start: int, *, downcast: bool) -> ak.Array:
        """Return the particle record of the branches in `arrays`, the first being `entry_start`."""
        columns: dict[str, Any] = {
            "event_index": np.arange(
                entry_start, entry_start + len(arrays), dtype=np.int64
            )
        }
        # The members of a branch share its entry count, since Delphes writes each
        # branch as one TClonesArray, so one member's count stands for all.
        if not ak.all(ak.num(arrays[EVENT_BRANCHES["event_number"]], axis=1) == 1):
            raise ValueError("Event holds other than one entry per event")
        for field, branch in EVENT_BRANCHES.items():
            columns[field] = ak.flatten(arrays[branch])
        for field, branch in PARTICLE_BRANCHES.items():
            columns[field] = arrays[branch]
        columns["part_t"] = columns["part_t"] * SPEED_OF_LIGHT_MM_PER_S
        return build_record(columns, downcast=downcast)
