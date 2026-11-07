// Parnassus's input in HepMC3's ASCII format: each event's record, built from a
// chunk of omphjc's particle record, and its text as HepMC3's own WriterAscii
// writes it (src/WriterAscii.cc at 3.3.1, https://gitlab.cern.ch/hepmc/HepMC3).
// omphjc.tools.parnassus.hepmc_input documents the record; module.cpp binds
// these functions to Python.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace omphjc::parnassus {

// A chunk of the particle record: each event's particle count and HepMC3 event
// number, and every particle column flat over the chunk's events. `mother` is
// the index of the particle's first mother in its event, -1 for none.
template <typename Real>
struct Chunk {
  std::int64_t n_events;
  const std::int64_t* particle_counts;
  const std::int64_t* event_numbers;
  const std::int32_t* pid;
  const std::int32_t* status;
  const std::int32_t* mother;
  const bool* is_final;
  const Real* px;
  const Real* py;
  const Real* pz;
  const Real* e;
  const Real* mass;
  const Real* x;
  const Real* y;
  const Real* z;
  const Real* t;
};

// The text of a chunk's events up to the first refused one, in pieces to be
// joined in order, the number of events in it, and the refusal ("" if none).
struct EventText {
  std::vector<std::string> pieces;
  std::int64_t n_events = 0;
  std::string error;
};

// The HEPEVT arrays of a chunk's events up to the first refused one, flat over
// those events: each event's particle count, and per particle its PDG id,
// status, momentum, mass, first and last parent (-1 for none) and production
// position. Also the number of events and the refusal ("" if none).
struct HepevtArrays {
  std::vector<std::int64_t> particle_counts;
  std::vector<std::int32_t> pid, status;
  std::vector<double> px, py, pz, e, m;
  std::vector<std::int64_t> parents;
  std::vector<double> vx, vy, vz, vt;
  std::int64_t n_events = 0;
  std::string error;
};

// Writes the chunk's events with `precision` digits after the point. Each of
// `thread_count` threads builds and writes a run of consecutive events of
// about equal particle count, and the runs are joined in order up to the first
// refusal, so the text does not depend on the number of threads.
template <typename Real>
EventText format_events(const Chunk<Real>& chunk, int precision, int thread_count);

template <typename Real>
HepevtArrays to_hepevt(const Chunk<Real>& chunk);

}  // namespace omphjc::parnassus
