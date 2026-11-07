// The record rules and the HepMC3 text of Parnassus's input (hepmc_ascii.hpp).
#include "parnassus/hepmc_ascii.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <exception>
#include <limits>
#include <stdexcept>
#include <system_error>
#include <thread>

namespace omphjc::parnassus {
namespace {

// HepMC status codes as Pythia's statusHepMC gives them
// (https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html).
constexpr int kFinalStatus = 1;
constexpr int kBeamStatus = 4;

// HepMC3 keeps an event's number as an int (GenEvent::event_number,
// include/HepMC3/GenEvent.h at 3.3.1).
constexpr std::int64_t kMinEventNumber = std::numeric_limits<int>::min();
constexpr std::int64_t kMaxEventNumber = std::numeric_limits<int>::max();

// The mother of a kept particle when it is not another kept particle: a beam
// has none, and a particle produced at the origin has the two beams.
constexpr int kNoMother = -2;
constexpr int kBeamMothers = -1;

// Bytes of text to reserve per particle of the record: Pythia dijet events
// write about 42.
constexpr std::size_t kBytesPerParticle = 48;

// The particles of one event that the file keeps, in file order, the beams
// first: each one's row in the chunk, and its mother as an index in `rows`,
// kBeamMothers or kNoMother.
struct KeptParticles {
  std::int64_t event_number = 0;
  std::vector<std::int64_t> rows;
  std::vector<int> mothers;
};

template <typename Real>
bool is_displaced_final(const Chunk<Real>& chunk, std::int64_t row) {
  return chunk.is_final[row] &&
         (chunk.x[row] != 0 || chunk.y[row] != 0 || chunk.z[row] != 0 || chunk.t[row] != 0);
}

// Selects the kept particles of events, reusing its buffers from one event to
// the next.
template <typename Real>
class ParticleSelector {
 public:
  explicit ParticleSelector(const Chunk<Real>& chunk) : chunk_(chunk) {}

  // Fills `kept` with the kept particles of the chunk's event `event_index`,
  // whose first row is `first_row`; on a refusal, returns false with the
  // reason in `error`.
  bool select(std::int64_t event_index, std::int64_t first_row, KeptParticles& kept,
              std::string& error) {
    const int particle_count = static_cast<int>(chunk_.particle_counts[event_index]);
    kept.event_number = chunk_.event_numbers[event_index];
    if (kept.event_number < kMinEventNumber || kept.event_number > kMaxEventNumber) {
      error = "event_index " + std::to_string(kept.event_number) +
              " does not fit HepMC3's event number, an int from " +
              std::to_string(kMinEventNumber) + " to " + std::to_string(kMaxEventNumber);
      return false;
    }
    int beams[2] = {-1, -1};
    int beam_count = 0;
    for (int i = 0; i < particle_count; ++i) {
      if (chunk_.status[first_row + i] == kBeamStatus) {
        if (beam_count < 2) beams[beam_count] = i;
        ++beam_count;
      }
    }
    if (beam_count != 2) {
      error = "event " + std::to_string(kept.event_number) + " has " +
              std::to_string(beam_count) + " beam particles (status " +
              std::to_string(kBeamStatus) + "), not 2";
      return false;
    }
    displaced_finals_.clear();
    displaced_mothers_.clear();
    for (int i = 0; i < particle_count; ++i) {
      if (is_displaced_final(chunk_, first_row + i)) {
        displaced_finals_.push_back(i);
        displaced_mothers_.push_back(chunk_.mother[first_row + i]);
      }
    }
    for (std::size_t j = 0; j < displaced_finals_.size(); ++j) {
      if (!has_finite_position(first_row + displaced_finals_[j])) {
        error = "final particle " + std::to_string(displaced_finals_[j]) + " of event " +
                std::to_string(kept.event_number) + " lies at a position that is not finite";
        return false;
      }
      const int mother = displaced_mothers_[j];
      if (mother < 0 || mother >= particle_count || mother == beams[0] || mother == beams[1]) {
        error = "final particle " + std::to_string(displaced_finals_[j]) + " of event " +
                std::to_string(kept.event_number) +
                " lies away from the origin, and its mother part_m1 = " + std::to_string(mother) +
                " is none, outside the event or a beam, so no vertex can give its position";
        return false;
      }
    }
    // Each displaced daughter must lie where its mother's first one does.
    first_displaced_daughter_.assign(particle_count, -1);
    for (std::size_t j = 0; j < displaced_finals_.size(); ++j) {
      int& first = first_displaced_daughter_[displaced_mothers_[j]];
      if (first < 0) {
        first = displaced_finals_[j];
      } else if (!at_same_position(first_row + displaced_finals_[j], first_row + first)) {
        error = "the daughters of particle " + std::to_string(displaced_mothers_[j]) +
                " in event " + std::to_string(kept.event_number) +
                " lie at different positions, but share their mother's one decay vertex";
        return false;
      }
    }
    // The beams, then the final particles and the mothers in record order.
    is_mother_.assign(particle_count, 0);
    for (int mother : displaced_mothers_) is_mother_[mother] = 1;
    kept_index_.assign(particle_count, -1);
    kept.rows.clear();
    kept.mothers.clear();
    for (int beam : beams) {
      kept_index_[beam] = static_cast<int>(kept.rows.size());
      kept.rows.push_back(first_row + beam);
      kept.mothers.push_back(kNoMother);
    }
    for (int i = 0; i < particle_count; ++i) {
      if (i == beams[0] || i == beams[1] || !(chunk_.is_final[first_row + i] || is_mother_[i]))
        continue;
      kept_index_[i] = static_cast<int>(kept.rows.size());
      kept.rows.push_back(first_row + i);
      kept.mothers.push_back(kBeamMothers);
    }
    for (std::size_t j = 0; j < kept.rows.size(); ++j) {
      const std::int64_t row = kept.rows[j];
      if (kept.mothers[j] == kBeamMothers && is_displaced_final(chunk_, row))
        kept.mothers[j] = kept_index_[chunk_.mother[row]];
    }
    return true;
  }

 private:
  bool has_finite_position(std::int64_t row) const {
    return std::isfinite(chunk_.x[row]) && std::isfinite(chunk_.y[row]) &&
           std::isfinite(chunk_.z[row]) && std::isfinite(chunk_.t[row]);
  }

  bool at_same_position(std::int64_t a, std::int64_t b) const {
    return chunk_.x[a] == chunk_.x[b] && chunk_.y[a] == chunk_.y[b] &&
           chunk_.z[a] == chunk_.z[b] && chunk_.t[a] == chunk_.t[b];
  }

  const Chunk<Real>& chunk_;
  // Per displaced final particle of the event: its index and its mother's.
  std::vector<int> displaced_finals_, displaced_mothers_;
  // Per particle of the event: its first displaced daughter, whether it is the
  // mother of one, and its index in the kept rows (-1 for none).
  std::vector<int> first_displaced_daughter_;
  std::vector<char> is_mother_;
  std::vector<int> kept_index_;
};

void append_int(std::string& out, std::int64_t value) {
  char buffer[24];
  out.append(buffer, std::to_chars(buffer, buffer + sizeof buffer, value).ptr);
}

// Appends one number as WriterAscii's " %.<precision>e" prints it.
// std::to_chars gives printf's digits for a finite number, but spells some NaNs
// otherwise (macOS's libc++ writes a negative NaN as -nan(ind)), so a number
// that is not finite is printed as WriterAscii prints it, with snprintf.
void append_real(std::string& out, double value, int precision) {
  char buffer[64];
  if (!std::isfinite(value)) {
    const int length = std::snprintf(buffer, sizeof buffer, " %.*e", precision, value);
    out.append(buffer, static_cast<std::size_t>(length));
    return;
  }
  buffer[0] = ' ';
  out.append(buffer, std::to_chars(buffer + 1, buffer + sizeof buffer, value,
                                   std::chars_format::scientific, precision)
                         .ptr);
}

// Appends the text of `kept` as WriterAscii::write_event writes it: the event
// and unit lines, then each particle in turn, with its production vertex's
// line before the first particle that vertex produces. A particle names its
// vertex, numbered -1, -2, ... in the order the vertices appear, as its parent.
template <typename Real>
void format_event(const Chunk<Real>& chunk, const KeptParticles& kept, int precision,
                  std::vector<int>& vertex_ids, std::string& out) {
  const std::size_t kept_count = kept.rows.size();
  // The id of each mother's vertex, by its index in kept.rows; the last entry
  // is the beams' vertex.
  vertex_ids.assign(kept_count + 1, 0);
  int vertex_count = 0;
  for (std::size_t j = 0; j < kept_count; ++j) {
    const int mother = kept.mothers[j];
    if (mother == kNoMother) continue;
    int& vertex_id =
        vertex_ids[mother == kBeamMothers ? kept_count : static_cast<std::size_t>(mother)];
    if (vertex_id == 0) vertex_id = -++vertex_count;
  }
  out += "E ";
  append_int(out, kept.event_number);
  out += ' ';
  append_int(out, vertex_count);
  out += ' ';
  append_int(out, static_cast<std::int64_t>(kept_count));
  out += "\nU GEV MM\n";
  int vertices_written = 0;  // the vertices are written in the order they are numbered
  for (std::size_t j = 0; j < kept_count; ++j) {
    const std::int64_t row = kept.rows[j];
    const int mother = kept.mothers[j];
    int parent_vertex = 0;
    if (mother != kNoMother) {
      parent_vertex =
          vertex_ids[mother == kBeamMothers ? kept_count : static_cast<std::size_t>(mother)];
      if (-parent_vertex > vertices_written) {
        ++vertices_written;
        out += "V ";
        append_int(out, parent_vertex);
        if (mother == kBeamMothers) {
          out += " 0 [1,2]\n";
        } else {
          out += " 0 [";
          append_int(out, mother + 1);
          out += "] @";
          append_real(out, chunk.x[row], precision);
          append_real(out, chunk.y[row], precision);
          append_real(out, chunk.z[row], precision);
          append_real(out, chunk.t[row], precision);
          out += '\n';
        }
      }
    }
    out += "P ";
    append_int(out, static_cast<std::int64_t>(j + 1));
    out += ' ';
    append_int(out, parent_vertex);
    out += ' ';
    append_int(out, chunk.pid[row]);
    append_real(out, chunk.px[row], precision);
    append_real(out, chunk.py[row], precision);
    append_real(out, chunk.pz[row], precision);
    append_real(out, chunk.e[row], precision);
    append_real(out, chunk.mass[row], precision);
    out += ' ';
    append_int(out, mother != kNoMother && chunk.is_final[row] ? kFinalStatus : chunk.status[row]);
    out += '\n';
  }
}

}  // namespace

template <typename Real>
EventText format_events(const Chunk<Real>& chunk, int precision, int thread_count) {
  if (thread_count < 1) throw std::invalid_argument("threads must be at least 1");
  // first_rows[k] is the first row of event k; first_rows[n_events] is past the last.
  std::vector<std::int64_t> first_rows(static_cast<std::size_t>(chunk.n_events) + 1, 0);
  for (std::int64_t k = 0; k < chunk.n_events; ++k)
    first_rows[k + 1] = first_rows[k] + chunk.particle_counts[k];
  const int run_count = static_cast<int>(
      std::max<std::int64_t>(1, std::min<std::int64_t>(thread_count, chunk.n_events)));
  // Run r writes events run_bounds[r] to run_bounds[r + 1], excluded.
  std::vector<std::int64_t> run_bounds(static_cast<std::size_t>(run_count) + 1, chunk.n_events);
  run_bounds[0] = 0;
  for (int r = 1; r < run_count; ++r) {
    const std::int64_t target_row = first_rows.back() * r / run_count;
    run_bounds[r] =
        std::lower_bound(first_rows.begin(), first_rows.end() - 1, target_row) - first_rows.begin();
  }
  struct Run {
    std::string text, error;
    std::int64_t stop_event = 0;  // the event the run stopped at
    bool refused = false;
    std::exception_ptr failure;
  };
  std::vector<Run> runs(static_cast<std::size_t>(run_count));
  const auto write_run = [&](int r) {
    Run& run = runs[r];
    try {
      ParticleSelector<Real> selector(chunk);
      KeptParticles kept;
      std::vector<int> vertex_ids;
      run.text.reserve(static_cast<std::size_t>(first_rows[run_bounds[r + 1]] -
                                                first_rows[run_bounds[r]]) *
                       kBytesPerParticle);
      std::int64_t k = run_bounds[r];
      for (; k < run_bounds[r + 1]; ++k) {
        if (!selector.select(k, first_rows[k], kept, run.error)) {
          run.refused = true;
          break;
        }
        format_event(chunk, kept, precision, vertex_ids, run.text);
      }
      run.stop_event = k;
    } catch (...) {
      run.failure = std::current_exception();
    }
  };
  std::vector<std::thread> workers;
  for (int r = 1; r < run_count; ++r) {
    try {
      workers.emplace_back(write_run, r);
    } catch (const std::system_error&) {
      write_run(r);  // no thread to spare: this one writes the run
    }
  }
  write_run(0);
  for (auto& worker : workers) worker.join();
  EventText text;
  for (Run& run : runs) {
    if (run.failure) std::rethrow_exception(run.failure);
    text.pieces.push_back(std::move(run.text));
    text.n_events = run.stop_event;
    if (run.refused) {
      text.error = run.error;
      break;
    }
  }
  return text;
}

template <typename Real>
HepevtArrays to_hepevt(const Chunk<Real>& chunk) {
  ParticleSelector<Real> selector(chunk);
  KeptParticles kept;
  HepevtArrays arrays;
  std::int64_t k = 0;
  for (std::int64_t first_row = 0; k < chunk.n_events; first_row += chunk.particle_counts[k], ++k) {
    if (!selector.select(k, first_row, kept, arrays.error)) break;
    arrays.particle_counts.push_back(static_cast<std::int64_t>(kept.rows.size()));
    for (std::size_t j = 0; j < kept.rows.size(); ++j) {
      const std::int64_t row = kept.rows[j];
      const int mother = kept.mothers[j];
      const bool from_kept_mother = mother >= 0;
      arrays.pid.push_back(chunk.pid[row]);
      arrays.status.push_back(mother != kNoMother && chunk.is_final[row] ? kFinalStatus
                                                                         : chunk.status[row]);
      arrays.px.push_back(chunk.px[row]);
      arrays.py.push_back(chunk.py[row]);
      arrays.pz.push_back(chunk.pz[row]);
      arrays.e.push_back(chunk.e[row]);
      arrays.m.push_back(chunk.mass[row]);
      arrays.parents.push_back(mother == kNoMother ? -1 : mother == kBeamMothers ? 0 : mother);
      arrays.parents.push_back(mother == kNoMother ? -1 : mother == kBeamMothers ? 1 : mother);
      arrays.vx.push_back(from_kept_mother ? static_cast<double>(chunk.x[row]) : 0.0);
      arrays.vy.push_back(from_kept_mother ? static_cast<double>(chunk.y[row]) : 0.0);
      arrays.vz.push_back(from_kept_mother ? static_cast<double>(chunk.z[row]) : 0.0);
      arrays.vt.push_back(from_kept_mother ? static_cast<double>(chunk.t[row]) : 0.0);
    }
  }
  arrays.n_events = k;
  return arrays;
}

template EventText format_events<float>(const Chunk<float>&, int, int);
template EventText format_events<double>(const Chunk<double>&, int, int);
template HepevtArrays to_hepevt<float>(const Chunk<float>&);
template HepevtArrays to_hepevt<double>(const Chunk<double>&);

}  // namespace omphjc::parnassus
