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

// A chunk of the particle record: each event's particle count and number, and
// every particle column flat over the chunk's events.
template <typename Real>
struct Chunk {
  std::int64_t n_events;
  const std::int64_t* counts;
  const std::int64_t* numbers;
  const std::int32_t* pid;
  const std::int32_t* status;
  const std::int32_t* m1;
  const bool* final;
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
struct Text {
  std::vector<std::string> pieces;
  std::int64_t n_events = 0;
  std::string error;
};

// The HEPEVT arrays of a chunk's events up to the first refused one, flat over
// those events: each event's particle count, and per particle its PDG id,
// status, momentum, mass, first and last parent (-1 for none) and production
// position. Also the number of events and the refusal ("" if none).
struct Hepevt {
  std::vector<std::int64_t> counts;
  std::vector<std::int32_t> pid, status;
  std::vector<double> px, py, pz, e, m;
  std::vector<std::int64_t> parents;
  std::vector<double> vx, vy, vz, vt;
  std::int64_t n_events = 0;
  std::string error;
};

// Writes the chunk's events with `precision` digits after the point. Each of
// `threads` threads builds and writes a run of consecutive events of about
// equal particle count, and the runs are joined in order up to the first
// refusal, so the text does not depend on the number of threads.
template <typename Real>
Text format_events(const Chunk<Real>& chunk, int precision, int threads);

template <typename Real>
Hepevt hepevt_events(const Chunk<Real>& chunk);

}  // namespace omphjc::parnassus
