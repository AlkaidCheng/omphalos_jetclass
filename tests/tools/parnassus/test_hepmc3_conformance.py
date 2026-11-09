"""Parnassus's input against HepMC3's own classes, WriterAscii and ReaderAscii."""

import ctypes
import importlib
import importlib.metadata
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest
from parnassus_records import (
    BEAMS,
    DECAY_VERTEX,
    NINE_DIGITS,
    b_to_psi2s_to_gluons,
    particle,
    pi0_to_two_photons,
    random_events,
    record,
    two_pi0s_at_two_vertices,
)

from omphjc.events.stable_particles import StableParticleDefinition
from omphjc.tools.parnassus.hepmc_input import (
    HEPMC3_VERSION,
    HepevtArrays,
    iterate_hepevt_arrays,
    write_hepmc_input,
)

K0S_DECAY = [
    *BEAMS,
    particle(310, 2, d1=3, d2=4, mass=0.4976),
    particle(211, 1, m1=2, at=DECAY_VERTEX),
    particle(-211, 1, m1=2, at=DECAY_VERTEX),
]
EVENTS = {
    "fixtures": [
        pi0_to_two_photons(),
        b_to_psi2s_to_gluons(),
        two_pi0s_at_two_vertices(),
        [particle(22, 1), *BEAMS],
    ],
    "random": random_events(np.random.default_rng(2026), 300),
}


@pytest.fixture
def hepmc3() -> ModuleType:
    """HepMC3's own Python bindings, from the HepMC3 package on PyPI."""
    try:
        bindings = importlib.import_module("pyHepMC3")
    except ModuleNotFoundError:
        pytest.skip("HepMC3's Python bindings, pyHepMC3, are not installed")
    except ImportError:
        if not load_hepmc3_library():
            raise
        bindings = importlib.import_module("pyHepMC3")
    module: ModuleType = bindings.HepMC3
    return module


def load_hepmc3_library() -> bool:
    """Load the libHepMC3 that the HepMC3 package installed, and say if it did.

    HepMC3 3.3.1's Linux wheels install the library into the environment's
    lib64 directory, while pyHepMC3.so looks for it only in the directory it
    was built in (its RPATH), so the bindings import once the library is loaded.
    """
    try:
        installed = importlib.metadata.files("hepmc3") or []
    except importlib.metadata.PackageNotFoundError:
        return False
    libraries = [
        path for path in installed if re.fullmatch(r"libHepMC3\.so\.\d+", path.name)
    ]
    for library in libraries:
        ctypes.CDLL(str(library.locate()), mode=ctypes.RTLD_GLOBAL)
    return bool(libraries)


def write_with_hepmc3(
    hepmc3: ModuleType, events: list[HepevtArrays], path: Path, precision: int
) -> None:
    """Write `events` with HepMC3's own classes and WriterAscii.

    Each event is built from its HEPEVT arrays, its particles added in turn and
    its vertices as their first particle appears, which numbers the vertices -1,
    -2, ... in that order. A vertex lies where its first particle was produced.
    """
    writer = hepmc3.WriterAscii(str(path))
    writer.set_precision(precision)
    for arrays in events:
        event = hepmc3.GenEvent(hepmc3.Units.GEV, hepmc3.Units.MM)
        event.set_event_number(arrays.event_number)
        particles = []
        for i in range(arrays.pid.size):
            momentum = hepmc3.FourVector(
                arrays.px[i], arrays.py[i], arrays.pz[i], arrays.e[i]
            )
            item = hepmc3.GenParticle(
                momentum, int(arrays.pid[i]), int(arrays.status[i])
            )
            item.set_generated_mass(arrays.m[i])
            event.add_particle(item)
            particles.append(item)
        vertices: dict[tuple[int, int], Any] = {}
        for i in range(arrays.pid.size):
            first, last = (int(index) for index in arrays.parents[i])
            if first < 0:
                continue
            if (first, last) not in vertices:
                position = hepmc3.FourVector(
                    arrays.vx[i], arrays.vy[i], arrays.vz[i], arrays.vt[i]
                )
                vertex = hepmc3.GenVertex(position)
                for parent in range(first, last + 1):
                    vertex.add_particle_in(particles[parent])
                event.add_vertex(vertex)
                vertices[first, last] = vertex
            vertices[first, last].add_particle_out(particles[i])
        writer.write_event(event)
    writer.close()


def _after_version(text: str) -> str:
    """Return the text after the version line, which names the HepMC3 release."""
    return text.split("\n", 1)[1]


def test_the_writer_follows_the_installed_hepmc3_release(hepmc3: ModuleType) -> None:
    assert hepmc3.version() == HEPMC3_VERSION, (
        f"HepMC3 {hepmc3.version()} is installed and the writer follows"
        f" {HEPMC3_VERSION}: compare src/WriterAscii.cc of the two releases,"
        " update the C++ writer, then HEPMC3_VERSION"
    )


@pytest.mark.parametrize("precision", [2, 8, 16, 24])
@pytest.mark.parametrize("name", list(EVENTS))
def test_the_file_is_the_one_hepmc3_writes(
    name: str, precision: int, tmp_path: Path, hepmc3: ModuleType
) -> None:
    particles = record(*EVENTS[name], first_index=3)
    ours, theirs = tmp_path / "ours.hepmc", tmp_path / "hepmc3.hepmc"
    write_hepmc_input([particles], ours, precision=precision)
    write_with_hepmc3(hepmc3, list(iterate_hepevt_arrays(particles)), theirs, precision)
    text = ours.read_text()
    assert text.startswith(f"HepMC::Version {HEPMC3_VERSION}\n")
    assert _after_version(text) == _after_version(theirs.read_text())


def test_numbers_that_are_not_finite_are_written_as_hepmc3_writes_them(
    tmp_path: Path, hepmc3: ModuleType
) -> None:
    negative_nan = float(-np.float32("nan"))
    momenta = (negative_nan, float("nan"), float("inf"), float("-inf"))
    particles = record([*BEAMS, particle(22, 1, p=momenta, mass=negative_nan)])
    ours, theirs = tmp_path / "ours.hepmc", tmp_path / "hepmc3.hepmc"
    write_hepmc_input([particles], ours)
    write_with_hepmc3(hepmc3, list(iterate_hepevt_arrays(particles)), theirs, 8)
    assert _after_version(ours.read_text()) == _after_version(theirs.read_text())


def test_a_promoted_hadron_is_written_as_hepmc3_writes_it(
    tmp_path: Path, hepmc3: ModuleType
) -> None:
    definition = StableParticleDefinition(ctau_min_mm=10.0, ctau_mm={310: 26.844})
    particles = definition.apply(record(K0S_DECAY, pi0_to_two_photons()))
    ours, theirs = tmp_path / "ours.hepmc", tmp_path / "hepmc3.hepmc"
    write_hepmc_input([particles], ours)
    write_with_hepmc3(hepmc3, list(iterate_hepevt_arrays(particles)), theirs, 8)
    assert _after_version(ours.read_text()) == _after_version(theirs.read_text())


def test_a_file_without_events_is_the_one_hepmc3_writes(
    tmp_path: Path, hepmc3: ModuleType
) -> None:
    ours, theirs = tmp_path / "ours.hepmc", tmp_path / "hepmc3.hepmc"
    assert write_hepmc_input([], ours) == 0
    write_with_hepmc3(hepmc3, [], theirs, 8)
    assert _after_version(ours.read_text()) == _after_version(theirs.read_text())


def test_a_refusal_leaves_what_hepmc3_writes_for_the_events_before(
    tmp_path: Path, hepmc3: ModuleType
) -> None:
    accepted = [pi0_to_two_photons(), b_to_psi2s_to_gluons()]
    refused = [*BEAMS, particle(22, 1, at=DECAY_VERTEX)]
    ours, theirs = tmp_path / "ours.hepmc", tmp_path / "hepmc3.hepmc"
    with pytest.raises(ValueError, match="particle 2 of event 2 lies away"):
        write_hepmc_input([record(*accepted), record(refused, first_index=2)], ours)
    write_with_hepmc3(hepmc3, list(iterate_hepevt_arrays(record(*accepted))), theirs, 8)
    assert _after_version(ours.read_text()) == _after_version(theirs.read_text())


def _four(vector: Any) -> list[float]:
    return [vector.x(), vector.y(), vector.z(), vector.t()]


def test_hepmc3_reads_back_every_particle_and_vertex(
    tmp_path: Path, hepmc3: ModuleType
) -> None:
    nine_digits = [*BEAMS, particle(22, 1, p=(NINE_DIGITS, 0.0, 0.0, NINE_DIGITS))]
    particles = record(
        nine_digits, *random_events(np.random.default_rng(9), 50), first_index=7
    )
    path = tmp_path / "input.hepmc"
    write_hepmc_input([particles], path)
    reader = hepmc3.ReaderAscii(str(path))
    for arrays in iterate_hepevt_arrays(particles):
        event = hepmc3.GenEvent()
        assert reader.read_event(event) and not reader.failed()
        assert event.event_number() == arrays.event_number
        assert event.momentum_unit() == hepmc3.Units.GEV
        assert event.length_unit() == hepmc3.Units.MM
        read = list(event.particles())
        assert [p.pid() for p in read] == arrays.pid.tolist()
        assert [p.status() for p in read] == arrays.status.tolist()
        momenta = [[*_four(p.momentum()), p.generated_mass()] for p in read]
        np.testing.assert_array_equal(
            np.float32(momenta),
            np.float32(
                np.column_stack([arrays.px, arrays.py, arrays.pz, arrays.e, arrays.m])
            ),
        )
        for p, (first, last), *position in zip(
            read,
            arrays.parents,
            arrays.vx,
            arrays.vy,
            arrays.vz,
            arrays.vt,
            strict=True,
        ):
            vertex = p.production_vertex()
            if first < 0:
                # HepMC3 hangs a particle without parents from the root vertex.
                assert vertex.id() == 0 and not vertex.particles_in()
                continue
            parents = [q.id() - 1 for q in vertex.particles_in()]
            assert parents == list(range(first, last + 1))
            assert (
                np.float32(_four(vertex.position())).tolist()
                == np.float32(position).tolist()
            )
    reader.close()
