"""Random seeds of a job.

A job runs three programs, each with a random generator of its own: MadGraph
(``iseed``), Pythia (``Random:seed``) and Delphes (``RandomSeed``). Job `n` of
a process gives all three the seed ``seed_offset + n``, where ``seed_offset``
is the process's catalogue value (0 unless the entry sets one), so the seeds of
a job follow from its process and number alone.
"""

from dataclasses import dataclass
from typing import ClassVar

from omphjc.processes.catalogue import ProcessSpec
from omphjc.pythia.cmnd import PYTHIA_SEED_LIMIT


@dataclass(frozen=True)
class Seeds:
    """The seeds of one job; ``None`` lets a generator seed itself.

    An unseeded MadGraph draws ``iseed`` at random, and Pythia and Delphes are
    then seeded from the clock.
    """

    madgraph: int | None
    pythia: int | None
    delphes: int | None

    RANDOM: ClassVar["Seeds"]


Seeds.RANDOM = Seeds(madgraph=None, pythia=None, delphes=None)


def derive_seeds(spec: ProcessSpec, job_id: int) -> Seeds:
    """Return the seeds of job `job_id` of `spec`: ``seed_offset + job_id``.

    Parameters
    ----------
    spec : ProcessSpec
        The process; its ``seed_offset`` is added to `job_id`.
    job_id : int
        Positive job number within the process.

    Raises
    ------
    ValueError
        If `job_id` is not positive or the seed exceeds Pythia's limit.
    """
    if job_id <= 0:
        raise ValueError(f"job_id must be positive, got {job_id}")
    seed = spec.seed_offset + job_id
    if seed > PYTHIA_SEED_LIMIT:
        raise ValueError(f"Seed {seed} exceeds Pythia's limit of {PYTHIA_SEED_LIMIT}")
    return Seeds(madgraph=seed, pythia=seed, delphes=seed)
