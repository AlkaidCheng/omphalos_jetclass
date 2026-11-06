"""The stable-particle definition: which particles a simulator receives as final.

Pythia decays every species whose nominal c*tau is below 1000 mm and that has
decay channels (``MAXTAU0FORDECAY``,
https://gitlab.com/Pythia8/releases/-/raw/pythia8312/src/ParticleData.cc),
while Parnassus expects the CMS convention, ``ParticleDecays:limitTau0 = on``
with ``tau0Max = 10`` mm, under which longer-lived hadrons stay final
(https://github.com/parnassus-hep/parnassus). A
:class:`StableParticleDefinition` counts a species as stable when its nominal
c*tau exceeds a threshold, and :meth:`~StableParticleDefinition.apply` undoes
the decays the shower made of such particles: it marks each as final and none
of its descendants.

The definition acts on a species table, as ``limitTau0`` does on the species'
nominal lifetimes, not on each particle's decay length. Only listed species can
count as long-lived, so the table must hold every species with decay channels
above the threshold; a table with none above it leaves the shower's status-1
particles as the final state.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from omphjc.numeric import require_number

if TYPE_CHECKING:
    import awkward as ak
    import numpy as np

# HepMC status codes as Pythia's statusHepMC gives them and Delphes stores them
# (https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html): 1 is
# final; 2 is a hadron, muon or tau that decayed, never a particle the shower
# branched.
FINAL_STATUS = 1
DECAYED_STATUS = 2

# What a refusal of a link outside its event advises: for an index past the
# event's end, and for one below -1.
_PAST_END_ADVICE = (
    "This happens when particles were removed after the indices were written:"
    " apply the definition before any cut, and write a Delphes Particle branch"
    " from Delphes/allParticles rather than from a filtered array. It also"
    " happens when the indices count from 1, as HEPEVT and LHE records do, and"
    " were not converted when the file was read."
)
_BELOW_NONE_ADVICE = (
    "The record numbers its particles another way; its reader must convert the"
    " indices to positions from 0, with -1 for none."
)


@dataclass(frozen=True)
class StableParticleDefinition:
    """Counts as stable the listed species whose nominal c*tau exceeds a threshold.

    Attributes
    ----------
    ctau_min_mm : float
        The nominal c*tau, in mm, above which a listed species is long-lived.
    ctau_mm : Mapping[int, float]
        The nominal c*tau, in mm, of each species by its absolute PDG id;
        antiparticles share their particle's entry.

    Raises
    ------
    TypeError
        If `ctau_mm` is not a mapping, a key of it is not an integer, or
        `ctau_min_mm` or a c*tau is not a number.
    ValueError
        If `ctau_min_mm` or a c*tau is not positive and finite, or a key is not
        positive.
    """

    ctau_min_mm: float
    ctau_mm: Mapping[int, float] = field(hash=False)

    def __post_init__(self) -> None:
        threshold = require_number(self.ctau_min_mm, what="ctau_min_mm", positive=True)
        object.__setattr__(self, "ctau_min_mm", threshold)
        if not isinstance(self.ctau_mm, Mapping):
            raise TypeError(
                f"ctau_mm must map PDG ids to c*tau in mm, got {self.ctau_mm!r}"
            )
        table = {}
        for key, ctau in self.ctau_mm.items():
            pid = require_number(key, what="a ctau_mm key", kind=int)
            if pid <= 0:
                raise ValueError(
                    f"ctau_mm keys must be positive PDG ids, got {pid}; an"
                    f" antiparticle shares its particle's entry"
                )
            table[pid] = require_number(ctau, what=f"ctau_mm[{pid}]", positive=True)
        object.__setattr__(self, "ctau_mm", MappingProxyType(table))

    @cached_property
    def long_lived(self) -> frozenset[int]:
        """The absolute PDG ids whose c*tau exceeds `ctau_min_mm`."""
        return frozenset(
            pid for pid, ctau in self.ctau_mm.items() if ctau > self.ctau_min_mm
        )

    def as_record(self) -> dict[str, Any]:
        """Return the threshold and table as JSON-native values.

        The PDG ids are strings, in ascending numeric order.
        """
        return {
            "ctau_min_mm": self.ctau_min_mm,
            "ctau_mm": {str(pid): self.ctau_mm[pid] for pid in sorted(self.ctau_mm)},
        }

    def apply(self, particles: "ak.Array") -> "ak.Array":
        """Return `particles` marked with ``part_final`` and ``part_promoted``.

        A candidate is a particle of a long-lived species that decayed, with
        HepMC status 2, has a daughter and is not copied into one: of a chain
        of copies, the last one, which carries the momentum after any recoil
        (``ParticleProperties``,
        https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html).
        A listed particle the shower branched instead, such as a muon that
        radiated a photon, keeps its shower status and is left as it is, so
        its last copy and the photon stay final.
        Every descendant of a candidate, every particle whose mother links lead
        back to it, is dropped, and a candidate that is not itself dropped is
        promoted, so of the cascade Xi- -> Lambda pi- only the Xi- is. The
        final state is the status-1 particles and the promoted ones, without
        the dropped ones. A record whose long-lived species the shower left
        undecayed keeps its status-1 particles as the final state, and
        applying the definition to the output again gives the same marks.

        Apply the definition to whole events, before any particle is removed:
        a removed particle leaves the indices of the others unchanged, so they
        point at the wrong particles or past the end of their event.

        Parameters
        ----------
        particles : ak.Array
            Particle records with ``part_pid``, ``part_status`` and the mother
            and daughter indices (:mod:`omphjc.events.particles`).

        Returns
        -------
        ak.Array
            `particles` with the boolean lists ``part_final`` and
            ``part_promoted``, one entry per particle, added or replaced.

        Raises
        ------
        ValueError
            If a mother or daughter index points outside its event, as one can
            in a record cut after its indices were written or in indices
            counted from 1.
        """
        # Imported here so that building a definition loads no array library.
        import awkward as ak
        import numpy as np

        counts = ak.to_numpy(ak.num(particles["part_pid"], axis=1)).astype(np.int64)
        status = _flat(particles["part_status"])
        promoted, dropped = self._promoted_and_dropped(particles, counts, status)
        final = ((status == FINAL_STATUS) | promoted) & ~dropped
        marked = ak.with_field(particles, ak.unflatten(final, counts), "part_final")
        return ak.with_field(marked, ak.unflatten(promoted, counts), "part_promoted")

    def _promoted_and_dropped(
        self, particles: "ak.Array", counts: "np.ndarray", status: "np.ndarray"
    ) -> tuple["np.ndarray", "np.ndarray"]:
        """Return the flat masks of the promoted and the dropped particles."""
        import numpy as np

        pid, m1, m2, d1, d2 = (
            _flat(particles[name])
            for name in ("part_pid", "part_m1", "part_m2", "part_d1", "part_d2")
        )
        event_start = np.repeat(np.cumsum(counts) - counts, counts)
        _check_links(
            particles,
            counts,
            event_start,
            part_m1=m1,
            part_m2=m2,
            part_d1=d1,
            part_d2=d2,
        )
        # Only the particles that decayed are tested further, which are few.
        decayed = np.flatnonzero((status == DECAYED_STATUS) & (d1 >= 0))
        first_daughter = pid[event_start[decayed] + d1[decayed]]
        copied = (d1[decayed] == d2[decayed]) & (first_daughter == pid[decayed])
        long_lived = np.fromiter(self.long_lived, dtype=np.int64)
        candidate = np.zeros(pid.size, dtype=bool)
        candidate[decayed] = np.isin(np.abs(pid[decayed]), long_lived) & ~copied
        # A decay product has a single mother, so part_m1 and part_m2 give its
        # whole ancestry along decay chains. Each pass follows the links from
        # the particles the pass before dropped, one generation further, so an
        # event settles within its particle count, and a cyclic record too,
        # since a particle is dropped once.
        with_mother = np.flatnonzero(m1 >= 0)
        mother = event_start[with_mother] + m1[with_mother]
        with_second = np.flatnonzero((m2 >= 0) & (m2 != m1))
        second = event_start[with_second] + m2[with_second]
        dropped = np.zeros_like(candidate)
        frontier = candidate
        for _ in range(int(counts.max(initial=0)) + 1):
            reached = np.zeros_like(candidate)
            reached[with_mother] = frontier[mother]
            reached[with_second] |= frontier[second]
            reached &= ~dropped
            if not reached.any():
                return candidate & ~dropped, dropped
            dropped |= reached
            frontier = reached
        raise ValueError("the mother links did not settle")


def _check_links(
    particles: "ak.Array",
    counts: "np.ndarray",
    event_start: "np.ndarray",
    **links: "np.ndarray",
) -> None:
    """Refuse a mother or daughter index that points outside its event.

    The indices are positions in the particle's own event, -1 for none, as
    Delphes writes them (``GenParticle.M1``: Pythia's ``mother1()`` minus 1).
    A lookup with an index past its event's end would read a particle of the
    next event, or fail in the last event of a chunk, so such an index is
    refused. It comes from a record whose particles were removed after the
    indices were written: by a cut on the particle lists, or by a Delphes card
    that writes a filtered array, such as a ``StatusPidFilter`` output, whose
    links still count positions in ``Delphes/allParticles`` (``TreeWriter``
    copies them unchanged). It also comes from indices counted from 1, as in
    HEPEVT, LHE files and Pythia's own record, once one of them reaches the
    event's size. An index below -1, which none of these sources writes, is
    refused too, since the walk would take it for none. An index that stays
    in range but points at the wrong particle cannot be seen here.
    """
    import numpy as np

    sizes = np.repeat(counts, counts)
    for name, index in links.items():
        outside = (index < -1) | (index >= sizes)
        if outside.any():
            row = int(np.argmax(outside))
            position = int(np.searchsorted(np.cumsum(counts), row, side="right"))
            event = (
                int(particles["event_index"][position])
                if "event_index" in particles.fields
                else position
            )
            size = int(counts[position])
            advice = _PAST_END_ADVICE if index[row] >= 0 else _BELOW_NONE_ADVICE
            raise ValueError(
                f"{name} of particle {row - int(event_start[row])} in event {event} is"
                f" {int(index[row])}, outside the event's {size}"
                f" {'particle' if size == 1 else 'particles'}. {advice}"
            )


def _flat(column: "ak.Array") -> "np.ndarray":
    """Return the values of a particle field as one int64 NumPy array."""
    import awkward as ak
    import numpy as np

    return np.asarray(ak.flatten(column, axis=1), dtype=np.int64)
