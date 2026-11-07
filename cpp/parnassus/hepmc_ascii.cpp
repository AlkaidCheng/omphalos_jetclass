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

// How a kept particle is produced: a beam has no production vertex, any other
// particle comes from the beams' vertex or from its mother's decay vertex.
constexpr int kBeam = -2;
constexpr int kFromBeams = -1;

// Bytes of text to reserve per particle of the record: Pythia dijet events
// write about 42.
constexpr std::size_t kTextPerParticle = 48;

// One event of the input: its kept particles in file order, the beams first.
struct Event {
  std::int64_t number = 0;
  std::vector<std::int64_t> rows;  // each kept particle's row in the chunk
  std::vector<int> source;         // kBeam, kFromBeams, or the mother's index in rows
};

template <typename Real>
bool displaced(const Chunk<Real>& c, std::int64_t row) {
  return c.final[row] && (c.x[row] != 0 || c.y[row] != 0 || c.z[row] != 0 || c.t[row] != 0);
}

// Builds events, reusing its buffers from one event to the next.
template <typename Real>
class Builder {
 public:
  explicit Builder(const Chunk<Real>& chunk) : c_(chunk) {}

  // Fills `event` with event k, whose first row is `base`; on a refusal,
  // returns false with the reason in `error`.
  bool build(std::int64_t k, std::int64_t base, Event& event, std::string& error) {
    const int n = static_cast<int>(c_.counts[k]);
    event.number = c_.numbers[k];
    if (event.number < kMinEventNumber || event.number > kMaxEventNumber) {
      error = "event_index " + std::to_string(event.number) +
              " does not fit HepMC3's event number, an int from " +
              std::to_string(kMinEventNumber) + " to " + std::to_string(kMaxEventNumber);
      return false;
    }
    int beams[2] = {-1, -1};
    int n_beams = 0;
    for (int i = 0; i < n; ++i) {
      if (c_.status[base + i] == kBeamStatus) {
        if (n_beams < 2) beams[n_beams] = i;
        ++n_beams;
      }
    }
    if (n_beams != 2) {
      error = "event " + std::to_string(event.number) + " has " + std::to_string(n_beams) +
              " beam particles (status " + std::to_string(kBeamStatus) + "), not 2";
      return false;
    }
    displaced_.clear();
    mothers_.clear();
    for (int i = 0; i < n; ++i) {
      if (displaced(c_, base + i)) {
        displaced_.push_back(i);
        mothers_.push_back(c_.m1[base + i]);
      }
    }
    for (std::size_t j = 0; j < displaced_.size(); ++j) {
      if (!finite_position(base + displaced_[j])) {
        error = "final particle " + std::to_string(displaced_[j]) + " of event " +
                std::to_string(event.number) + " lies at a position that is not finite";
        return false;
      }
      const int mother = mothers_[j];
      if (mother < 0 || mother >= n || mother == beams[0] || mother == beams[1]) {
        error = "final particle " + std::to_string(displaced_[j]) + " of event " +
                std::to_string(event.number) +
                " lies away from the origin, and its mother part_m1 = " + std::to_string(mother) +
                " is none, outside the event or a beam, so no vertex can give its position";
        return false;
      }
    }
    // Each displaced daughter must lie where its mother's first one does.
    first_daughter_.assign(n, -1);
    for (std::size_t j = 0; j < displaced_.size(); ++j) {
      int& first = first_daughter_[mothers_[j]];
      if (first < 0) {
        first = displaced_[j];
      } else if (!same_position(base + displaced_[j], base + first)) {
        error = "the daughters of particle " + std::to_string(mothers_[j]) + " in event " +
                std::to_string(event.number) +
                " lie at different positions, but share their mother's one decay vertex";
        return false;
      }
    }
    // The beams, then the final particles and the mothers in record order.
    is_mother_.assign(n, 0);
    for (int mother : mothers_) is_mother_[mother] = 1;
    index_.assign(n, -1);
    event.rows.clear();
    event.source.clear();
    for (int beam : beams) {
      index_[beam] = static_cast<int>(event.rows.size());
      event.rows.push_back(base + beam);
      event.source.push_back(kBeam);
    }
    for (int i = 0; i < n; ++i) {
      if (i == beams[0] || i == beams[1] || !(c_.final[base + i] || is_mother_[i])) continue;
      index_[i] = static_cast<int>(event.rows.size());
      event.rows.push_back(base + i);
      event.source.push_back(kFromBeams);
    }
    for (std::size_t j = 0; j < event.rows.size(); ++j) {
      const std::int64_t row = event.rows[j];
      if (event.source[j] == kFromBeams && displaced(c_, row)) event.source[j] = index_[c_.m1[row]];
    }
    return true;
  }

 private:
  bool finite_position(std::int64_t row) const {
    return std::isfinite(c_.x[row]) && std::isfinite(c_.y[row]) && std::isfinite(c_.z[row]) &&
           std::isfinite(c_.t[row]);
  }

  bool same_position(std::int64_t a, std::int64_t b) const {
    return c_.x[a] == c_.x[b] && c_.y[a] == c_.y[b] && c_.z[a] == c_.z[b] && c_.t[a] == c_.t[b];
  }

  const Chunk<Real>& c_;
  std::vector<int> displaced_, mothers_, first_daughter_, index_;
  std::vector<char> is_mother_;
};

void put_int(std::string& out, std::int64_t value) {
  char buffer[24];
  out.append(buffer, std::to_chars(buffer, buffer + sizeof buffer, value).ptr);
}

// One number as WriterAscii's " %.<precision>e" prints it. std::to_chars gives
// printf's digits for a finite number, but spells some NaNs otherwise (macOS's
// libc++ writes a negative NaN as -nan(ind)), so a number that is not finite
// is printed as WriterAscii prints it, with snprintf.
void put_real(std::string& out, double value, int precision) {
  char buffer[64];
  if (!std::isfinite(value)) {
    const int n = std::snprintf(buffer, sizeof buffer, " %.*e", precision, value);
    out.append(buffer, static_cast<std::size_t>(n));
    return;
  }
  buffer[0] = ' ';
  out.append(buffer, std::to_chars(buffer + 1, buffer + sizeof buffer, value,
                                   std::chars_format::scientific, precision)
                         .ptr);
}

// Appends the text of `event` as WriterAscii::write_event writes it: the event
// and unit lines, then each particle in turn, with its production vertex's
// line before the first particle that vertex produces. A particle names its
// vertex, numbered -1, -2, ... in the order the vertices appear, as its parent.
template <typename Real>
void format_event(const Chunk<Real>& c, const Event& event, int precision,
                  std::vector<int>& vertex_of, std::string& out) {
  const std::size_t n = event.rows.size();
  vertex_of.assign(n + 1, 0);  // by mother index; the last entry is the beams' vertex
  int n_vertices = 0;
  for (std::size_t j = 0; j < n; ++j) {
    const int source = event.source[j];
    if (source == kBeam) continue;
    int& vertex = vertex_of[source == kFromBeams ? n : static_cast<std::size_t>(source)];
    if (vertex == 0) vertex = -++n_vertices;
  }
  out += "E ";
  put_int(out, event.number);
  out += ' ';
  put_int(out, n_vertices);
  out += ' ';
  put_int(out, static_cast<std::int64_t>(n));
  out += "\nU GEV MM\n";
  int written = 0;  // vertices written so far, which are numbered in order
  for (std::size_t j = 0; j < n; ++j) {
    const std::int64_t row = event.rows[j];
    const int source = event.source[j];
    int parent = 0;
    if (source != kBeam) {
      parent = vertex_of[source == kFromBeams ? n : static_cast<std::size_t>(source)];
      if (-parent > written) {
        ++written;
        out += "V ";
        put_int(out, parent);
        if (source == kFromBeams) {
          out += " 0 [1,2]\n";
        } else {
          out += " 0 [";
          put_int(out, source + 1);
          out += "] @";
          put_real(out, c.x[row], precision);
          put_real(out, c.y[row], precision);
          put_real(out, c.z[row], precision);
          put_real(out, c.t[row], precision);
          out += '\n';
        }
      }
    }
    out += "P ";
    put_int(out, static_cast<std::int64_t>(j + 1));
    out += ' ';
    put_int(out, parent);
    out += ' ';
    put_int(out, c.pid[row]);
    put_real(out, c.px[row], precision);
    put_real(out, c.py[row], precision);
    put_real(out, c.pz[row], precision);
    put_real(out, c.e[row], precision);
    put_real(out, c.mass[row], precision);
    out += ' ';
    put_int(out, source != kBeam && c.final[row] ? kFinalStatus : c.status[row]);
    out += '\n';
  }
}

}  // namespace

template <typename Real>
Text format_events(const Chunk<Real>& c, int precision, int threads) {
  if (threads < 1) throw std::invalid_argument("threads must be at least 1");
  // first[k] is the first row of event k; first[n_events] is past the last.
  std::vector<std::int64_t> first(static_cast<std::size_t>(c.n_events) + 1, 0);
  for (std::int64_t k = 0; k < c.n_events; ++k) first[k + 1] = first[k] + c.counts[k];
  const int n_runs =
      static_cast<int>(std::max<std::int64_t>(1, std::min<std::int64_t>(threads, c.n_events)));
  std::vector<std::int64_t> bounds(static_cast<std::size_t>(n_runs) + 1, c.n_events);
  bounds[0] = 0;
  for (int r = 1; r < n_runs; ++r) {
    const std::int64_t target = first.back() * r / n_runs;
    bounds[r] = std::lower_bound(first.begin(), first.end() - 1, target) - first.begin();
  }
  struct Run {
    std::string text, error;
    std::int64_t stop = 0;  // the event the run stopped at
    bool refused = false;
    std::exception_ptr failure;
  };
  std::vector<Run> runs(static_cast<std::size_t>(n_runs));
  const auto write_run = [&](int r) {
    Run& run = runs[r];
    try {
      Builder<Real> builder(c);
      Event event;
      std::vector<int> vertex_of;
      run.text.reserve(
          static_cast<std::size_t>(first[bounds[r + 1]] - first[bounds[r]]) * kTextPerParticle);
      std::int64_t k = bounds[r];
      for (; k < bounds[r + 1]; ++k) {
        if (!builder.build(k, first[k], event, run.error)) {
          run.refused = true;
          break;
        }
        format_event(c, event, precision, vertex_of, run.text);
      }
      run.stop = k;
    } catch (...) {
      run.failure = std::current_exception();
    }
  };
  std::vector<std::thread> pool;
  for (int r = 1; r < n_runs; ++r) {
    try {
      pool.emplace_back(write_run, r);
    } catch (const std::system_error&) {
      write_run(r);  // no thread to spare: this one writes the run
    }
  }
  write_run(0);
  for (auto& thread : pool) thread.join();
  Text result;
  for (Run& run : runs) {
    if (run.failure) std::rethrow_exception(run.failure);
    result.pieces.push_back(std::move(run.text));
    result.n_events = run.stop;
    if (run.refused) {
      result.error = run.error;
      break;
    }
  }
  return result;
}

template <typename Real>
Hepevt hepevt_events(const Chunk<Real>& c) {
  Builder<Real> builder(c);
  Event event;
  Hepevt out;
  std::int64_t k = 0;
  for (std::int64_t base = 0; k < c.n_events; base += c.counts[k], ++k) {
    if (!builder.build(k, base, event, out.error)) break;
    out.counts.push_back(static_cast<std::int64_t>(event.rows.size()));
    for (std::size_t j = 0; j < event.rows.size(); ++j) {
      const std::int64_t row = event.rows[j];
      const int source = event.source[j];
      const bool from_mother = source >= 0;
      out.pid.push_back(c.pid[row]);
      out.status.push_back(source != kBeam && c.final[row] ? kFinalStatus : c.status[row]);
      out.px.push_back(c.px[row]);
      out.py.push_back(c.py[row]);
      out.pz.push_back(c.pz[row]);
      out.e.push_back(c.e[row]);
      out.m.push_back(c.mass[row]);
      out.parents.push_back(source == kBeam ? -1 : source == kFromBeams ? 0 : source);
      out.parents.push_back(source == kBeam ? -1 : source == kFromBeams ? 1 : source);
      out.vx.push_back(from_mother ? static_cast<double>(c.x[row]) : 0.0);
      out.vy.push_back(from_mother ? static_cast<double>(c.y[row]) : 0.0);
      out.vz.push_back(from_mother ? static_cast<double>(c.z[row]) : 0.0);
      out.vt.push_back(from_mother ? static_cast<double>(c.t[row]) : 0.0);
    }
  }
  out.n_events = k;
  return out;
}

template Text format_events<float>(const Chunk<float>&, int, int);
template Text format_events<double>(const Chunk<double>&, int, int);
template Hepevt hepevt_events<float>(const Chunk<float>&);
template Hepevt hepevt_events<double>(const Chunk<double>&);

}  // namespace omphjc::parnassus
