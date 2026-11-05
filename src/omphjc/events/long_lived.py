"""Long-lived particles that the shower decayed, restored as final for a simulator.

Pythia decays every species whose nominal c*tau is below 1000 mm and that has
decay channels (``MAXTAU0FORDECAY``,
https://gitlab.com/Pythia8/releases/-/raw/pythia8312/src/ParticleData.cc),
while Parnassus expects the CMS convention, ``ParticleDecays:limitTau0 = on``
with ``tau0Max = 10`` mm, under which longer-lived hadrons stay final
(https://github.com/parnassus-hep/parnassus). A :class:`LongLivedRestorer`
undoes the decays the shower made of the species it counts as long-lived:
:meth:`~LongLivedRestorer.restore` marks such a particle as final and none of
its descendants.

The restorer acts on a species table, as ``limitTau0`` does on the species'
nominal lifetimes, not on each particle's decay length. Only listed species can
count as long-lived, so the table must hold every species with decay channels
above the threshold; a table with none above it leaves the shower's status-1
particles as the final state.

awkward and numpy are imported only when :meth:`~LongLivedRestorer.restore`
runs, so importing the module and building a restorer loads no array library.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import awkward as ak
    import numpy as np

# HepMC status codes as Pythia's statusHepMC gives them and Delphes stores them
# (https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html): 1 is
# final; 2 is a hadron, muon or tau that decayed, never a particle the shower
# branched.
FINAL_STATUS = 1
DECAYED_STATUS = 2


@dataclass(frozen=True)
class LongLivedRestorer:
    """Restores as final the particles of long-lived species that the shower decayed.

    Attributes
    ----------
    ctau_min_mm : float
        The nominal c*tau, in mm, above which a listed species is long-lived.
    ctau_mm : Mapping[int, float]
        The nominal c*tau, in mm, of each species by its absolute PDG id;
        antiparticles share their particle's entry.

    Raises
    ------
    ValueError
        If `ctau_min_mm` or a c*tau is not a positive finite number, or a key of
        `ctau_mm` is not a positive int.
    """

    ctau_min_mm: float
    ctau_mm: Mapping[int, float] = field(hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ctau_min_mm", _positive_length("ctau_min_mm", self.ctau_min_mm)
        )
        table = {}
        for pid, ctau in self.ctau_mm.items():
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                raise ValueError(
                    f"ctau_mm keys must be positive PDG ids, got {pid!r}; an"
                    f" antiparticle shares its particle's entry"
                )
            table[pid] = _positive_length(f"ctau_mm[{pid}]", ctau)
        object.__setattr__(self, "ctau_mm", MappingProxyType(table))

    @property
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

    def restore(self, particles: "ak.Array") -> "ak.Array":
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
        restoring the output again gives the same marks.

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
            If a mother or daughter index points outside its event.
        """
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

        def gather(values: "np.ndarray", index: "np.ndarray") -> "np.ndarray":
            """Return the values at the event's rows `index`, False or 0 at -1."""
            gathered = np.zeros_like(values)
            present = index >= 0
            gathered[present] = values[(event_start + index)[present]]
            return gathered

        copied = (d1 >= 0) & (d1 == d2) & (gather(pid, d1) == pid)
        long_lived = np.fromiter(self.long_lived, dtype=np.int64)
        candidate = (
            np.isin(np.abs(pid), long_lived)
            & (status == DECAYED_STATUS)
            & (d1 >= 0)
            & ~copied
        )
        dropped = np.zeros_like(candidate)
        # A decay product has a single mother, so part_m1 and part_m2 give its
        # whole ancestry along decay chains. Each pass marks one more generation,
        # so an event settles within its particle count, and a cyclic record too,
        # since the marks only grow.
        for _ in range(int(counts.max(initial=0)) + 1):
            flagged = candidate | dropped
            marked = dropped | gather(flagged, m1) | gather(flagged, m2)
            if np.array_equal(marked, dropped):
                break
            dropped = marked
        else:
            raise ValueError("the mother links did not settle")
        return candidate & ~dropped, dropped


def _check_links(
    particles: "ak.Array",
    counts: "np.ndarray",
    event_start: "np.ndarray",
    **links: "np.ndarray",
) -> None:
    """Refuse a mother or daughter index that points outside its event.

    The indices are positions in the particle's own event, -1 for none, as
    Delphes writes them (``GenParticle.M1``: Pythia's ``mother1()`` minus 1).
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
            raise ValueError(
                f"{name} of particle {row - int(event_start[row])} in event {event} is"
                f" {int(index[row])}, outside the event's {int(counts[position])}"
                " particles"
            )


def _flat(column: "ak.Array") -> "np.ndarray":
    """Return the values of a particle field as one int64 NumPy array."""
    import awkward as ak
    import numpy as np

    return np.asarray(ak.flatten(column, axis=1), dtype=np.int64)


def _positive_length(name: str, value: Any) -> float:
    """Return `value` as a float, refusing one that is not a positive finite number."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(
            f"{name} must be a positive finite length in mm, got {value!r}"
        )
    return float(value)
