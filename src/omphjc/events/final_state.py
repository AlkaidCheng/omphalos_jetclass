"""The final state a simulator receives: the shower's, or long-lived hadrons put back.

Pythia decays every species whose nominal c*tau is below 1000 mm and that has
decay channels (``MAXTAU0FORDECAY``,
https://gitlab.com/Pythia8/releases/-/raw/pythia8312/src/ParticleData.cc),
while Parnassus expects the CMS convention, ``ParticleDecays:limitTau0 = on``
with ``tau0Max = 10`` mm, under which longer-lived hadrons stay final
(https://github.com/parnassus-hep/parnassus). A :class:`FinalStateRule` can
undo the decays the shower made of the species it lists as long-lived:
:func:`mark_final_state` then counts such a particle as final and drops its
descendants.

The rule acts on a species table, as ``limitTau0`` does on the species'
nominal lifetimes, not on each particle's decay length. Only listed species can
count as long-lived, so the table must hold every species with decay channels
above the threshold.

The module imports awkward and numpy only inside :func:`mark_final_state`, so a
catalogue holding a rule loads no array library.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import awkward as ak
    import numpy as np


@dataclass(frozen=True)
class FinalStateRule:
    """Which particles count as final for the simulator.

    Attributes
    ----------
    restore_long_lived : bool
        Whether a particle of a long-lived species that the shower decayed
        counts as final, its descendants dropped. When false, the final state
        is the status-1 particles.
    ctau_min_mm : float
        The nominal c*tau, in mm, above which a listed species is long-lived.
    ctau_mm : Mapping[int, float]
        The nominal c*tau, in mm, of each species by its absolute PDG id;
        antiparticles share their particle's entry.

    Raises
    ------
    ValueError
        If `restore_long_lived` is not a bool, `ctau_min_mm` or a c*tau is not
        a positive finite number, or a key of `ctau_mm` is not a positive int.
    """

    restore_long_lived: bool
    ctau_min_mm: float
    ctau_mm: Mapping[int, float] = field(hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.restore_long_lived, bool):
            raise ValueError(
                f"restore_long_lived must be true or false, got"
                f" {self.restore_long_lived!r}"
            )
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
        """Return the rule as JSON-native values, with PDG ids as strings.

        A rule that restores nothing is ``{"restore_long_lived": false}``: its
        threshold and table do not change the final state.
        """
        if not self.restore_long_lived:
            return {"restore_long_lived": False}
        return {
            "restore_long_lived": True,
            "ctau_min_mm": self.ctau_min_mm,
            "ctau_mm": {str(pid): self.ctau_mm[pid] for pid in sorted(self.ctau_mm)},
        }


def mark_final_state(particles: "ak.Array", rule: FinalStateRule) -> "ak.Array":
    """Return `particles` with the boolean lists ``part_final`` and ``part_promoted``.

    A candidate is a particle of a long-lived species that has a daughter and
    is not copied into one: of a chain of copies, the last one, which carries
    the momentum after any recoil (``ParticleProperties``,
    https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html).
    Every descendant of a candidate is dropped, found by walking up from each
    particle through its mothers ``part_m1`` and ``part_m2``: a decay product
    has a single mother, so the two give its whole ancestry along decay
    chains. A candidate that is not itself dropped is promoted, so of the
    cascade Xi- -> Lambda pi- only the Xi- is. The final state is the status-1
    particles and the promoted ones, without the dropped ones. The rule changes
    nothing on a record whose long-lived species the shower left undecayed, and
    marking its own output again gives the same marks.

    Parameters
    ----------
    particles : ak.Array
        Particle records with ``part_pid``, ``part_status`` and the mother and
        daughter indices (:mod:`omphjc.events.particles`).
    rule : FinalStateRule
        The rule to apply. Without `restore_long_lived`, the final state is
        the status-1 particles and nothing is promoted.

    Returns
    -------
    ak.Array
        `particles` with the two fields added or replaced.

    Raises
    ------
    ValueError
        If `rule` restores long-lived hadrons and a mother or daughter index
        points outside its event.
    """
    import awkward as ak
    import numpy as np

    counts = ak.to_numpy(ak.num(particles["part_pid"], axis=1)).astype(np.int64)
    status = _flat(particles["part_status"])
    if rule.restore_long_lived:
        promoted, dropped = _promote_long_lived(particles, counts, rule)
        final = ((status == 1) | promoted) & ~dropped
    else:
        final = status == 1
        promoted = np.zeros_like(final)
    marked = ak.with_field(particles, ak.unflatten(final, counts), "part_final")
    return ak.with_field(marked, ak.unflatten(promoted, counts), "part_promoted")


def _promote_long_lived(
    particles: "ak.Array", counts: "np.ndarray", rule: FinalStateRule
) -> tuple["np.ndarray", "np.ndarray"]:
    """Return the flat masks of the promoted and the dropped particles."""
    import numpy as np

    pid, m1, m2, d1, d2 = (
        _flat(particles[name])
        for name in ("part_pid", "part_m1", "part_m2", "part_d1", "part_d2")
    )
    first = np.repeat(np.cumsum(counts) - counts, counts)
    _check_links(
        particles, counts, first, part_m1=m1, part_m2=m2, part_d1=d1, part_d2=d2
    )

    def gather(values: "np.ndarray", index: "np.ndarray") -> "np.ndarray":
        """Return the values at the event's rows `index`, False or 0 at -1."""
        gathered = np.zeros_like(values)
        present = index >= 0
        gathered[present] = values[(first + index)[present]]
        return gathered

    copied = (d1 >= 0) & (d1 == d2) & (gather(pid, d1) == pid)
    long_lived = np.fromiter(rule.long_lived, dtype=np.int64)
    candidate = np.isin(np.abs(pid), long_lived) & (d1 >= 0) & ~copied
    second_mother = m2 != m1
    dropped = np.zeros_like(candidate)
    # Each pass marks one more generation, so an event settles within its
    # particle count, and a cyclic record too, since the marks only grow.
    for _ in range(int(counts.max(initial=0)) + 1):
        flagged = candidate | dropped
        marked = dropped | gather(flagged, m1) | (gather(flagged, m2) & second_mother)
        if np.array_equal(marked, dropped):
            break
        dropped = marked
    else:
        raise ValueError("the mother links did not settle")
    return candidate & ~dropped, dropped


def _check_links(
    particles: "ak.Array",
    counts: "np.ndarray",
    first: "np.ndarray",
    **links: "np.ndarray",
) -> None:
    """Refuse a mother or daughter index that points outside its event.

    The indices are positions in the particle's own event, -1 for none, as
    Delphes writes them (``GenParticle.M1``: Pythia's ``mother1()`` minus 1).
    `first` holds each particle's event start in the flat arrays.
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
                f"{name} of particle {row - int(first[row])} in event {event} is"
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
