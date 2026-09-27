import pytest

from omphjc.jobs import Seeds, derive_seeds
from omphjc.processes import get_process
from omphjc.pythia import PYTHIA_SEED_LIMIT


def test_job_seed_is_the_process_offset_plus_the_job_id() -> None:
    seeds = derive_seeds(get_process("HToBB"), 7)
    assert seeds == Seeds(madgraph=10000007, pythia=10000007, delphes=10000007)
    assert derive_seeds(get_process("HToCC"), 7).madgraph == 20000007
    assert derive_seeds(get_process("TTBar"), 1).madgraph == 1


def test_random_seeds_leave_every_generator_unseeded() -> None:
    assert Seeds(madgraph=None, pythia=None, delphes=None) == Seeds.RANDOM


def test_job_ids_are_positive_and_seeds_within_pythia_range() -> None:
    spec = get_process("HToBB")
    with pytest.raises(ValueError, match="job_id"):
        derive_seeds(spec, 0)
    with pytest.raises(ValueError, match="limit"):
        derive_seeds(spec, PYTHIA_SEED_LIMIT)
