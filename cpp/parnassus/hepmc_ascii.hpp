/**
 * @file
 * @brief Parnassus's input in HepMC3's ASCII format.
 *
 * Each event's record is built from a chunk of omphjc's particle record, and
 * its text is written as HepMC3's own WriterAscii writes it (src/WriterAscii.cc
 * at 3.3.1, https://gitlab.cern.ch/hepmc/HepMC3).
 * omphjc.tools.parnassus.hepmc_input documents the record; module.cpp binds
 * these functions to Python.
 */
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace omphjc::parnassus {

/**
 * @brief A chunk of the particle record, every particle column flat over the
 * chunk's events.
 *
 * The arrays are borrowed: they must outlive every call that reads the chunk.
 */
template <typename Real>
struct Chunk {
  std::int64_t n_events;
  const std::int64_t* particle_counts;  ///< Each event's number of particles.
  const std::int64_t* event_numbers;    ///< Each event's HepMC3 event number.
  const std::int32_t* pid;
  const std::int32_t* status;
  const std::int32_t* mother;  ///< The first mother's index in its event, -1 for none.
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

/**
 * @brief The text of a chunk's events up to the first refused one.
 */
struct EventText {
  std::vector<std::string> pieces;  ///< The text, in pieces to be joined in order.
  std::int64_t n_events = 0;        ///< The number of events in the text.
  std::string error;                ///< The refusal, empty if none.
};

/**
 * @brief The HEPEVT arrays of a chunk's events up to the first refused one,
 * flat over those events.
 *
 * Per particle: its PDG id, status, momentum, mass, first and last parent (-1
 * for none) and production position.
 */
struct HepevtArrays {
  std::vector<std::int64_t> particle_counts;  ///< Each event's number of particles.
  std::vector<std::int32_t> pid, status;
  std::vector<double> px, py, pz, e, m;
  std::vector<std::int64_t> parents;  ///< Pairs of parent indices, flat.
  std::vector<double> vx, vy, vz, vt;
  std::int64_t n_events = 0;  ///< The number of events in the arrays.
  std::string error;          ///< The refusal, empty if none.
};

/**
 * @brief Writes the chunk's events as HepMC3's WriterAscii writes them.
 *
 * Each thread builds and writes a run of consecutive events of about equal
 * particle count, and the runs are joined in order up to the first refusal,
 * so the text does not depend on the number of threads.
 *
 * @param chunk        The events.
 * @param precision    Digits after the decimal point of each number.
 * @param thread_count The number of threads.
 * @return The text of the events up to the first refused one.
 * @throws std::invalid_argument If @p thread_count is below 1.
 */
template <typename Real>
[[nodiscard]] EventText format_events(const Chunk<Real>& chunk, int precision, int thread_count);

/**
 * @brief Returns the HEPEVT arrays of the record the file keeps of each event.
 *
 * @param chunk The events.
 * @return The arrays of the events up to the first refused one.
 */
template <typename Real>
[[nodiscard]] HepevtArrays to_hepevt(const Chunk<Real>& chunk);

}  // namespace omphjc::parnassus
