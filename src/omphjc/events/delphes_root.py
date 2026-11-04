"""Reader of the generator record in a Delphes ROOT file.

Delphes writes the generator's particles to branch ``Particle``
(``GenParticle``) and the event's header to branch ``Event`` (``HepMCEvent``)
of tree ``Delphes``. DelphesPythia8's record of the shower and DelphesROOT's
output both carry them (Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/classes/DelphesClasses.h).

Branches are read by their bare names, such as ``Particle.PID``: uproot finds
a bare name in a file written by ROOT by searching the tree, and a file written
by uproot has no ``Particle/`` level, so only bare names read both.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import awkward as ak
import numpy as np
import uproot

from omphjc.events.particles import build_record, check_indices
from omphjc.root_io import entries_per_step

TREE_NAME = "Delphes"

# Delphes writes GenParticle.T in seconds, as position.T() * 1.0E-3 / c_light
# with c_light = 2.99792458E8 m/s (TreeWriter::ProcessParticles,
# https://github.com/delphes/delphes/blob/3.5.1/modules/TreeWriter.cc); the
# record holds c t in mm. The exact SI value of c, in mm/s:
SPEED_OF_LIGHT_MM_PER_S = 2.99792458e11

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


def count_events(path: Path) -> int:
    """Return the number of events in the Delphes ROOT file `path`, reading none."""
    with uproot.open(path) as file:
        return int(_tree(file, path).num_entries)


def read_particles(
    path: Path,
    *,
    entry_start: int = 0,
    entry_stop: int | None = None,
    downcast: bool = True,
) -> ak.Array:
    """Return the particle record of the events in [entry_start, entry_stop) of `path`.

    Parameters
    ----------
    path : Path
        A Delphes ROOT file.
    entry_start, entry_stop : int, int or None, optional
        The events to read; ``None`` reads to the end of the file.
    downcast : bool, optional
        Whether to cast every field to the schema's dtype.

    Returns
    -------
    ak.Array
        One record per event (:mod:`omphjc.events.particles`).

    Raises
    ------
    ValueError
        If the range lies outside the file, a branch is missing, ``Event``
        holds other than one entry per event, an index lies outside its event,
        or a value does not fit the schema's dtype when downcasting.
    """
    with uproot.open(path) as file:
        tree = _tree(file, path)
        n_events = int(tree.num_entries)
        stop = n_events if entry_stop is None else entry_stop
        if not 0 <= entry_start <= stop <= n_events:
            raise ValueError(
                f"entries [{entry_start}, {stop}) lie outside the {n_events}"
                f" events of {path}"
            )
        arrays = tree.arrays(list(BRANCHES), entry_start=entry_start, entry_stop=stop)
    return _record(arrays, entry_start, downcast=downcast)


def iterate_particles(
    path: Path, *, step_size: int | str = "100 MB", downcast: bool = True
) -> Iterator[ak.Array]:
    """Yield the particle record of `path` in steps of `step_size`.

    Parameters
    ----------
    path : Path
        A Delphes ROOT file.
    step_size : int or str, optional
        Events per step, or a memory size such as ``"100 MB"`` of the branches
        read (:func:`omphjc.root_io.entries_per_step`).
    downcast : bool, optional
        Whether to cast every field to the schema's dtype.

    Yields
    ------
    ak.Array
        The records of consecutive events.

    Raises
    ------
    ValueError
        As :func:`read_particles` does.
    """
    with uproot.open(path) as file:
        tree = _tree(file, path)
        step = entries_per_step(tree, BRANCHES, step_size)
        for arrays, report in tree.iterate(list(BRANCHES), step_size=step, report=True):
            yield _record(arrays, report.tree_entry_start, downcast=downcast)


def _tree(file: Any, path: Path) -> Any:
    """Return tree Delphes of `file`, after checking that it has every branch read."""
    if TREE_NAME not in file:
        raise ValueError(f"{path} has no tree {TREE_NAME!r}")
    tree = file[TREE_NAME]
    missing = [name for name in BRANCHES if name not in tree]
    if missing:
        raise ValueError(f"tree {TREE_NAME!r} of {path} lacks {', '.join(missing)}")
    return tree


def _record(arrays: ak.Array, entry_start: int, *, downcast: bool) -> ak.Array:
    """Return the particle record of the branches in `arrays`, the first being `entry_start`."""
    columns: dict[str, Any] = {
        "event_index": np.arange(entry_start, entry_start + len(arrays), dtype=np.int64)
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
