"""The particle record: one awkward record per event, with its fields' dtypes and units.

A record holds the fields of :data:`FIELDS` that its file carries. Event fields
are scalars. Particle fields are lists named ``part_*``, with one entry per
particle of the event.

The units are the ones that Delphes stores. The exception is ``part_t``, which
is in mm (c t), as Pythia and HepMC3 write it.

The dtypes follow Delphes's ``GenParticle`` and ``HepMCEvent`` (Delphes 3.5.1,
https://github.com/delphes/delphes/blob/3.5.1/classes/DelphesClasses.h). The
exceptions are ``part_status`` and ``part_charge``: the record stores them as
int16, which holds their values.

The mother and daughter indices follow Pythia's conventions
(https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html).
Under these conventions the daughters of a particle are not always a range.
Each index is one lower than Pythia's, because Delphes leaves out Pythia's
entry 0.
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
        "Event.Number as the program wrote it: DelphesPythia8 counts every event"
        " it attempted, so numbers are missing where one failed; DelphesROOT"
        " numbers the events of each input file from 0. Not a join key.",
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
        One array for each field of :data:`FIELDS` that the record holds. An
        event field has one value per event. A particle field has one list
        per event.
    downcast : bool
        Whether to cast every field to the dtype of the schema. Without the
        cast, each field keeps the dtype it has.

    Returns
    -------
    ak.Array
        One record per event.

    Raises
    ------
    ValueError
        If `columns` has a field that the schema does not know. When
        downcasting, also if a field holds a value that its dtype cannot hold.
    """
    unknown = sorted(set(columns) - {field.name for field in FIELDS})
    if unknown:
        raise ValueError(f"the particle record has no fields {unknown}")
    return ak.zip(
        {
            field.name: (
                _cast(field, columns[field.name]) if downcast else columns[field.name]
            )
            for field in FIELDS
            if field.name in columns
        },
        depth_limit=1,
    )


def _cast(field: RecordField, column: ak.Array) -> ak.Array:
    """Return `column` cast to `field`'s dtype.

    A float is cast to another float dtype without a check. A cast of an
    integer to a narrower integer dtype is refused when a value lies outside
    the narrower dtype. Any other cast that can change a value, such as a cast
    from a float to an integer, is refused too.
    """
    target = np.dtype(field.dtype)
    source = _value_dtype(column)
    if source == target:
        return column
    if source is None:
        # Every list is empty, so the values have no dtype yet.
        return ak.values_astype(column, target, including_unknown=True)
    if np.issubdtype(source, np.integer) and np.issubdtype(target, np.integer):
        if not np.can_cast(source, target):
            # A view of the stored values, far faster to reduce than ak.min.
            values = ak.to_numpy(ak.flatten(column, axis=None))
            limits = np.iinfo(target)
            if values.size and (values.min() < limits.min or values.max() > limits.max):
                raise ValueError(
                    f"{field.name} holds values from {values.min()} to"
                    f" {values.max()}, which {target} cannot hold; read with"
                    " downcast=False to keep them"
                )
    elif not (
        np.issubdtype(source, np.floating) and np.issubdtype(target, np.floating)
    ) and not np.can_cast(source, target):
        raise ValueError(
            f"{field.name} holds {source} values, which a cast to {target} can"
            " change; read with downcast=False to keep them"
        )
    return ak.values_astype(column, target)


def _value_dtype(column: ak.Array) -> np.dtype | None:
    """Return the dtype of `column`'s values, read from its type; None if unknown."""
    node = ak.type(column).content
    while not isinstance(node, (ak.types.NumpyType, ak.types.UnknownType)):
        node = node.content
    return np.dtype(node.primitive) if isinstance(node, ak.types.NumpyType) else None
