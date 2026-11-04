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
import uproot

from omphjc.events.formats import EventFormat
from omphjc.events.particles import build_record, check_indices
from omphjc.events.readers import EventReader
from omphjc.root_io import entries_per_step

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
    the record is read from, an ``Event`` branch with other than one entry per
    event, and a mother or daughter index outside its event. A memory step size
    counts the uncompressed bytes of the branches read
    (:func:`omphjc.root_io.entries_per_step`).
    """

    format = EventFormat.DELPHES_ROOT

    def count_events(self) -> int:
        with uproot.open(self.path) as file:
            return int(self._tree(file).num_entries)

    def read_particles(
        self,
        *,
        entry_start: int = 0,
        entry_stop: int | None = None,
        downcast: bool = True,
    ) -> ak.Array:
        with uproot.open(self.path) as file:
            tree = self._tree(file)
            n_events = int(tree.num_entries)
            stop = n_events if entry_stop is None else entry_stop
            if not 0 <= entry_start <= stop <= n_events:
                raise ValueError(
                    f"entries [{entry_start}, {stop}) lie outside the {n_events}"
                    f" events of {self.path}"
                )
            arrays = tree.arrays(
                list(BRANCHES), entry_start=entry_start, entry_stop=stop
            )
        return self._record(arrays, entry_start, downcast=downcast)

    def iterate_particles(
        self, *, step_size: int | str = "100 MB", downcast: bool = True
    ) -> Iterator[ak.Array]:
        with uproot.open(self.path) as file:
            tree = self._tree(file)
            step = entries_per_step(tree, BRANCHES, step_size)
            for arrays, report in tree.iterate(
                list(BRANCHES), step_size=step, report=True
            ):
                yield self._record(arrays, report.tree_entry_start, downcast=downcast)

    def _tree(self, file: Any) -> Any:
        """Return tree Delphes of `file`, after checking that it has every branch read."""
        if TREE_NAME not in file:
            raise ValueError(f"{self.path} has no tree {TREE_NAME!r}")
        tree = file[TREE_NAME]
        missing = [name for name in BRANCHES if name not in tree]
        if missing:
            raise ValueError(
                f"tree {TREE_NAME!r} of {self.path} lacks {', '.join(missing)}"
            )
        return tree

    @staticmethod
    def _record(arrays: ak.Array, entry_start: int, *, downcast: bool) -> ak.Array:
        """Return the particle record of the branches in `arrays`, the first being `entry_start`."""
        columns: dict[str, Any] = {
            "event_index": np.arange(
                entry_start, entry_start + len(arrays), dtype=np.int64
            )
        }
        for field, branch in EVENT_BRANCHES.items():
            column = arrays[branch]
            if not ak.all(ak.num(column, axis=1) == 1):
                raise ValueError(f"{branch} holds other than one entry per event")
            columns[field] = column[:, 0]
        counts = ak.num(arrays[PARTICLE_BRANCHES["part_pid"]], axis=1)
        for field, branch in PARTICLE_BRANCHES.items():
            column = arrays[branch]
            if not ak.all(ak.num(column, axis=1) == counts):
                raise ValueError(f"{branch} holds other than one entry per particle")
            columns[field] = column
        columns["part_t"] = columns["part_t"] * SPEED_OF_LIGHT_MM_PER_S
        record = build_record(columns, downcast=downcast)
        check_indices(record)
        return record
