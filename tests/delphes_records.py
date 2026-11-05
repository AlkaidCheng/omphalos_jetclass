"""Writing synthetic files with the layout of a Delphes ROOT file, through uproot.

The branches carry Delphes's names and types (Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/classes/DelphesClasses.h): a
``Particle`` list per event and an ``Event`` list holding one entry per event.
"""

from collections.abc import Collection, Mapping
from pathlib import Path

import awkward as ak
import numpy as np
import uproot

PARTICLE_DTYPES = {
    "PID": np.int32,
    "Status": np.int32,
    "IsPU": np.int32,
    "M1": np.int32,
    "M2": np.int32,
    "D1": np.int32,
    "D2": np.int32,
    "Charge": np.int32,
    "Mass": np.float32,
    "E": np.float32,
    "Px": np.float32,
    "Py": np.float32,
    "Pz": np.float32,
    "P": np.float32,
    "PT": np.float32,
    "Eta": np.float32,
    "Phi": np.float32,
    "Rapidity": np.float32,
    "T": np.float32,
    "X": np.float32,
    "Y": np.float32,
    "Z": np.float32,
}

EVENT_DTYPES = {
    "Number": np.int64,
    "ReadTime": np.float32,
    "ProcTime": np.float32,
    "ProcessID": np.int32,
    "MPI": np.int32,
    "Weight": np.float32,
    "CrossSection": np.float32,
    "CrossSectionError": np.float32,
    "Scale": np.float32,
    "AlphaQED": np.float32,
    "AlphaQCD": np.float32,
    "ID1": np.int32,
    "ID2": np.int32,
    "X1": np.float32,
    "X2": np.float32,
    "ScalePDF": np.float32,
    "PDF1": np.float32,
    "PDF2": np.float32,
}


def write_delphes_file(
    path: Path,
    particles: Mapping[str, ak.Array],
    events: Mapping[str, np.ndarray] | None = None,
    *,
    events_per_basket: int | None = None,
    event_entries: np.ndarray | None = None,
    omit: Collection[str] = (),
) -> None:
    """Write tree ``Delphes`` with branches ``Particle`` and ``Event`` to `path`.

    Parameters
    ----------
    path : Path
        The file to write.
    particles : Mapping[str, ak.Array]
        Lists of particle values per event, keyed by ``GenParticle`` member;
        members not given are zero, and ``M1`` to ``D2`` are -1.
    events : Mapping[str, np.ndarray] or None, optional
        One value per event, keyed by ``HepMCEvent`` member; members not given
        are zero, except ``Number``, which counts from 0.
    events_per_basket : int or None, optional
        Events written per basket; ``None`` writes all of them in one.
    event_entries : np.ndarray or None, optional
        Entries of ``Event`` in each event, each repeating the event's values;
        ``None`` writes one.
    omit : Collection[str], optional
        Branches to leave out, such as ``"Particle.Charge"``.
    """
    counts = ak.num(next(iter(particles.values())), axis=1)
    n_events = len(counts)
    particle_columns = {}
    for name, dtype in PARTICLE_DTYPES.items():
        if f"Particle.{name}" in omit:
            continue
        if name in particles:
            values = particles[name]
        else:
            default = -1 if name in ("M1", "M2", "D1", "D2") else 0
            values = ak.unflatten(np.full(int(ak.sum(counts)), default), counts)
        particle_columns[name] = ak.values_astype(values, dtype)
    event_values = dict(events or {})
    event_values.setdefault("Number", np.arange(n_events))
    entries = np.ones(n_events, np.int64) if event_entries is None else event_entries
    event_columns = {
        name: ak.unflatten(
            np.repeat(
                np.asarray(event_values.get(name, np.zeros(n_events)), dtype=dtype),
                entries,
            ),
            entries,
        )
        for name, dtype in EVENT_DTYPES.items()
        if f"Event.{name}" not in omit
    }
    particle = ak.zip(particle_columns)
    event = ak.zip(event_columns)
    step = events_per_basket or max(n_events, 1)
    with uproot.recreate(path, compression=uproot.ZLIB(1)) as file:
        tree = file.mktree(
            "Delphes",
            {"Particle": particle.type.content, "Event": event.type.content},
            counter_name=lambda counted: f"{counted}_size",
            field_name=lambda outer, inner: (
                inner if outer == "" else f"{outer}.{inner}"
            ),
        )
        for start in range(0, n_events, step):
            tree.extend(
                {
                    "Particle": particle[start : start + step],
                    "Event": event[start : start + step],
                }
            )
