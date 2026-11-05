"""The particle record: one awkward record per event, with its fields' dtypes and units.

Event fields are scalars. Particle fields are lists named ``part_*``, with one
entry per particle of the event. The units are those Delphes stores, except
``part_t``, which is in mm (c t) as Pythia and HepMC3 write it. The dtypes
follow Delphes's ``GenParticle`` and ``HepMCEvent`` (Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/classes/DelphesClasses.h), except
``part_status`` and ``part_charge``, which int16 holds. The mother and daughter
indices follow Pythia's conventions, one lower since Delphes leaves out
Pythia's entry 0, so a particle's daughters are not always a range
(https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html).
"""

from collections.abc import Mapping
from typing import NamedTuple

import awkward as ak
import numpy as np


class RecordField(NamedTuple):
    """A field of the particle record."""

    name: str
    dtype: str
    unit: str
    description: str


EVENT_FIELDS = (
    RecordField(
        "event_index",
        "int64",
        "",
        "Position of the event in its file, from 0; it joins the shower record"
        " with the simulations of it.",
    ),
    RecordField(
        "event_number",
        "int64",
        "",
        "Number the generator gave the event; DelphesPythia8 also counts events"
        " that failed, so numbers can be missing.",
    ),
    RecordField("weight", "float32", "", "Event weight."),
    RecordField("scale", "float32", "GeV", "Renormalisation scale."),
    RecordField("alpha_qcd", "float32", "", "Strong coupling."),
    RecordField("alpha_qed", "float32", "", "Electromagnetic coupling."),
    RecordField("id1", "int32", "", "PDG id of the first incoming parton."),
    RecordField("id2", "int32", "", "PDG id of the second incoming parton."),
    RecordField("x1", "float32", "", "Momentum fraction of the first parton."),
    RecordField("x2", "float32", "", "Momentum fraction of the second parton."),
)

PARTICLE_FIELDS = (
    RecordField("part_pid", "int32", "", "PDG id."),
    RecordField(
        "part_status",
        "int16",
        "",
        "HepMC status: 1 final, 2 decayed, 4 beam, 11 to 200 intermediate.",
    ),
    RecordField("part_m1", "int32", "", "Index of the first mother, -1 for none."),
    RecordField("part_m2", "int32", "", "Index of the second mother, -1 for none."),
    RecordField("part_d1", "int32", "", "Index of the first daughter, -1 for none."),
    RecordField("part_d2", "int32", "", "Index of the second daughter, -1 for none."),
    RecordField(
        "part_charge",
        "int16",
        "e",
        "Electric charge, -999 for a PDG id that ROOT does not know.",
    ),
    RecordField("part_mass", "float32", "GeV", "Generated mass."),
    RecordField("part_px", "float32", "GeV", "Momentum along x."),
    RecordField("part_py", "float32", "GeV", "Momentum along y."),
    RecordField("part_pz", "float32", "GeV", "Momentum along z."),
    RecordField("part_e", "float32", "GeV", "Energy."),
    RecordField("part_x", "float32", "mm", "Production vertex, x."),
    RecordField("part_y", "float32", "mm", "Production vertex, y."),
    RecordField("part_z", "float32", "mm", "Production vertex, z."),
    RecordField("part_t", "float32", "mm", "Production time as c t."),
)

FIELDS = EVENT_FIELDS + PARTICLE_FIELDS


def build_record(columns: Mapping[str, ak.Array], *, downcast: bool) -> ak.Array:
    """Return the particle record made of `columns`, in the schema's field order.

    Parameters
    ----------
    columns : Mapping[str, ak.Array]
        One array per field of :data:`FIELDS`: event fields with one value per
        event, particle fields with one list per event.
    downcast : bool
        Whether to cast every field to the schema's dtype; otherwise each keeps
        the dtype it has.

    Returns
    -------
    ak.Array
        One record per event.

    Raises
    ------
    ValueError
        If `columns` lacks a field of the schema or has one it does not know,
        or, when downcasting, if a field holds a value its dtype cannot hold.
    """
    names = [field.name for field in FIELDS]
    if set(columns) != set(names):
        unknown = sorted(set(columns) - set(names))
        missing = [name for name in names if name not in columns]
        raise ValueError(
            f"the record's fields differ from the schema: missing {missing},"
            f" unknown {unknown}"
        )
    if downcast:
        columns = {field.name: _cast(field, columns[field.name]) for field in FIELDS}
    return ak.zip({name: columns[name] for name in names}, depth_limit=1)


def _cast(field: RecordField, column: ak.Array) -> ak.Array:
    """Return `column` cast to `field`'s dtype, refusing a value the dtype cannot hold."""
    dtype = np.dtype(field.dtype)
    values = ak.to_numpy(ak.flatten(column, axis=None))
    if values.dtype == dtype:
        return column
    if np.issubdtype(dtype, np.integer) and np.issubdtype(values.dtype, np.integer):
        limits = np.iinfo(dtype)
        holds = values.size == 0 or (
            limits.min <= values.min() and values.max() <= limits.max
        )
    else:
        with np.errstate(invalid="ignore", over="ignore"):
            cast = values.astype(dtype)
            if np.issubdtype(dtype, np.integer):
                holds = np.array_equal(cast.astype(values.dtype), values)
            else:
                holds = not np.any(np.isinf(cast) & np.isfinite(values))
    if not holds:
        raise ValueError(
            f"{field.name} holds values from {values.min()} to {values.max()},"
            f" which {dtype} cannot hold; read with downcast=False to keep them"
        )
    return ak.values_astype(column, dtype)
