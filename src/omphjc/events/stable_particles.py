"""The stable-particle definition: which particles a simulator receives as final.

Pythia decays every species that has decay channels and a nominal c*tau below
1000 mm (``MAXTAU0FORDECAY``,
https://gitlab.com/Pythia8/releases/-/raw/pythia8312/src/ParticleData.cc).
Parnassus expects the CMS convention instead: ``ParticleDecays:limitTau0 = on``
with ``tau0Max = 10`` mm (https://github.com/parnassus-hep/parnassus). Under
the CMS convention, hadrons with a longer lifetime stay final.

A :class:`StableParticleDefinition` counts a species as stable when its nominal
c*tau exceeds a threshold. :meth:`~StableParticleDefinition.apply` undoes the
decays that the shower made of such particles. It marks each such particle as
final, and it marks none of the descendants of the particle as final.

The definition acts on a table of species, in the way ``limitTau0`` acts on
the nominal lifetimes of the species. It does not act on the decay length of
each particle.

Only a listed species can count as long-lived, so the table must hold every
species that has decay channels and a nominal c*tau above the threshold. With
a table that holds no species above the threshold, the status-1 particles of
the shower remain the final state.
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
    """Counts a listed species as stable when its nominal c*tau exceeds a threshold.

    Attributes
    ----------
    ctau_min_mm : float
        The nominal c*tau, in mm, above which a listed species is long-lived.
    ctau_mm : Mapping[int, float]
        The nominal c*tau, in mm, of each species, keyed by its absolute PDG
        id. An antiparticle shares the entry of its particle.

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

        A candidate is a particle that meets all of these conditions:

        - Its species is long-lived.
        - It has HepMC status 2, which means that it decayed.
        - It has a daughter.
        - It is not copied into its daughter.

        The last condition selects the last particle of a chain of copies.
        That particle carries the momentum after any recoil
        (``ParticleProperties``,
        https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html).

        A particle of a listed species that the shower branched is not a
        candidate. An example is a muon that radiated a photon. Such a
        particle keeps its shower status and is left unchanged, so its last
        copy and the photon stay final.

        A descendant of a candidate is a particle whose mother links lead back
        to the candidate. Every descendant is dropped. A candidate that is not
        itself dropped is promoted. In the cascade Xi- -> Lambda pi-, for
        example, only the Xi- is promoted.

        The final state consists of the status-1 particles and the promoted
        particles, without the dropped particles. When the shower left the
        long-lived species of a record undecayed, the record keeps its
        status-1 particles as the final state. Applying the definition to the
        output again gives the same marks.

        Apply the definition to whole events, before any particle is removed.
        Removing a particle leaves the indices of the other particles
        unchanged. These indices then point at the wrong particles or past the
        end of their event.

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
            If a mother or daughter index points outside its event. This can
            happen when particles were cut from the record after its indices
            were written, or when the indices count from 1.
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
        _check_links(particles, counts, part_m1=m1, part_m2=m2, part_d1=d1, part_d2=d2)
        event_start = np.repeat(np.cumsum(counts) - counts, counts)
        # The tests narrow the particles step by step: few decayed, and fewer of
        # those are of a long-lived species.
        decayed = np.flatnonzero((status == DECAYED_STATUS) & (d1 >= 0))
        long_lived = np.fromiter(self.long_lived, dtype=np.int64)
        decayed_long_lived = decayed[np.isin(np.abs(pid[decayed]), long_lived)]
        first_daughter = pid[event_start[decayed_long_lived] + d1[decayed_long_lived]]
        copied = (d1[decayed_long_lived] == d2[decayed_long_lived]) & (
            first_daughter == pid[decayed_long_lived]
        )
        candidate = np.zeros(pid.size, dtype=bool)
        candidate[decayed_long_lived[~copied]] = True
        # A decay product has a single mother, so part_m1 and part_m2 give its
        # whole ancestry along decay chains. Each pass covers every particle of
        # the chunk at once: it follows the links from the particles the pass
        # before dropped, one generation further down, and the walk ends at the
        # first pass that reaches nothing new, after a few passes in a shower.
        # An event holds no more generations than particles, and a cyclic record
        # drops each particle once, so max_passes only bounds the loop.
        # A particle without a first mother looks up the padding entry after the
        # last particle, which is never in the frontier; only the few with a
        # second mother look that one up.
        size = pid.size
        mother = np.where(m1 >= 0, event_start + m1, size)
        with_second = np.flatnonzero((m2 >= 0) & (m2 != m1))
        second = event_start[with_second] + m2[with_second]
        frontier = np.append(candidate, False)
        dropped = np.zeros_like(candidate)
        max_passes = int(counts.max(initial=0)) + 1
        for _ in range(max_passes):
            reached = frontier[mother]
            reached[with_second] |= frontier[second]
            reached &= ~dropped
            if not reached.any():
                return candidate & ~dropped, dropped
            dropped |= reached
            frontier[:size] = reached
        raise ValueError("the mother links did not settle")


def _check_links(
    particles: "ak.Array", counts: "np.ndarray", **links: "np.ndarray"
) -> None:
    """Refuse a mother or daughter index that points outside its event.

    An index is a position in the particle's own event, or -1 for none.
    Delphes writes the indices in this way (``GenParticle.M1`` is Pythia's
    ``mother1()`` minus 1).

    An index past the end of its event is refused. A lookup with such an index
    would read a particle of the next event, or fail in the last event of a
    chunk. Such an index has one of two sources:

    - Particles were removed from the record after the indices were written.
      A cut on the particle lists does this. So does a Delphes card that
      writes a filtered array, such as a ``StatusPidFilter`` output. The
      links of the filtered array still count positions in
      ``Delphes/allParticles``, because ``TreeWriter`` copies them unchanged.
    - The indices count from 1, as in HEPEVT, LHE files and Pythia's own
      record. Such indices are refused once one of them reaches the size of
      the event.

    An index below -1 is refused too, because the walk over the mother links
    would treat it as none. Neither of the two sources writes such an index.

    An index that stays in range but points at the wrong particle cannot be
    detected here.
    """
    import numpy as np

    # Each event's smallest and largest index are compared with its size.
    # reduceat reduces from each start to the next and gives an empty event the
    # value at its start, which belongs to the next event, so it takes only the
    # starts of the non-empty events.
    filled = np.flatnonzero(counts)
    starts = (np.cumsum(counts) - counts)[filled]
    for name, index in links.items():
        outside = (np.minimum.reduceat(index, starts) < -1) | (
            np.maximum.reduceat(index, starts) >= counts[filled]
        )
        if outside.any():
            first = int(np.argmax(outside))
            position = int(filled[first])
            start, size = int(starts[first]), int(counts[position])
            in_event = index[start : start + size]
            particle = int(np.argmax((in_event < -1) | (in_event >= size)))
            value = int(in_event[particle])
            event = (
                int(particles["event_index"][position])
                if "event_index" in particles.fields
                else position
            )
            advice = _PAST_END_ADVICE if value >= 0 else _BELOW_NONE_ADVICE
            raise ValueError(
                f"{name} of particle {particle} in event {event} is {value}, outside"
                f" the event's {size} {'particle' if size == 1 else 'particles'}."
                f" {advice}"
            )


def _flat(column: "ak.Array") -> "np.ndarray":
    """Return the values of a particle field as one NumPy array, in its dtype."""
    import awkward as ak
    import numpy as np

    return np.asarray(ak.flatten(column, axis=1))
