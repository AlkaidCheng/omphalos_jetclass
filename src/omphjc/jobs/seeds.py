"""Random seeds of a job.

A job runs three generators, each with its own random generator: MadGraph
(``iseed``), Pythia (``Random:seed``) and Delphes (``RandomSeed``). One job
seed serves all three, so a job is reproducible from its process and its id
alone, and every process starts its seeds at its own offset, as the official
production did.
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
        The process, whose ``seed_offset`` keeps its jobs apart from those of
        every other process.
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
