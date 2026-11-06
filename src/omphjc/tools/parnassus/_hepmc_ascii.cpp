// Parnassus's input in HepMC3's ASCII format: each event's record, built from a
// chunk of omphjc's particle record, and its text as HepMC3's own WriterAscii
// writes it (src/WriterAscii.cc at 3.3.1, https://gitlab.cern.ch/hepmc/HepMC3).
// omphjc.tools.parnassus.hepmc_input documents the record and calls this module.
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <algorithm>
#include <charconv>
#include <cstdint>
#include <initializer_list>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace py = pybind11;

namespace {

// HepMC status codes as Pythia's statusHepMC gives them
// (https://pythia8.web.cern.ch/manuals/pythia8318/ParticleProperties.html).
constexpr int kFinalStatus = 1;
constexpr int kBeamStatus = 4;

// How a kept particle is produced: a beam has no production vertex, any other
// particle comes from the beams' vertex or from its mother's decay vertex.
constexpr int kBeam = -2;
constexpr int kFromBeams = -1;

// A chunk of the particle record; every particle array is flat over its events.
template <typename Real>
struct Chunk {
  py::ssize_t n_events;
  const int64_t* counts;
  const int64_t* numbers;
  const int32_t* pid;
  const int32_t* status;
  const int32_t* m1;
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

  bool displaced(int64_t row) const {
    return final[row] && (x[row] != 0 || y[row] != 0 || z[row] != 0 || t[row] != 0);
  }
};

// One event of the input: its kept particles in file order, the beams first.
struct Event {
  int64_t number = 0;
  std::vector<int64_t> rows;    // each kept particle's row in the chunk
  std::vector<int> source;      // kBeam, kFromBeams, or the mother's index in rows
};

// Builds events, reusing its buffers from one event to the next.
template <typename Real>
class Builder {
 public:
  explicit Builder(const Chunk<Real>& chunk) : c_(chunk) {}

  // Fills `event` with event k, whose first row is `base`; on a refusal,
  // returns false with the reason in `error`.
  bool build(py::ssize_t k, int64_t base, Event& event, std::string& error) {
    const int n = static_cast<int>(c_.counts[k]);
    event.number = c_.numbers[k];
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
      if (c_.displaced(base + i)) {
        displaced_.push_back(i);
        mothers_.push_back(c_.m1[base + i]);
      }
    }
    for (std::size_t j = 0; j < displaced_.size(); ++j) {
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
      const int64_t row = event.rows[j];
      if (event.source[j] == kFromBeams && c_.displaced(row)) event.source[j] = index_[c_.m1[row]];
    }
    return true;
  }

 private:
  bool same_position(int64_t a, int64_t b) const {
    return c_.x[a] == c_.x[b] && c_.y[a] == c_.y[b] && c_.z[a] == c_.z[b] && c_.t[a] == c_.t[b];
  }

  const Chunk<Real>& c_;
  std::vector<int> displaced_, mothers_, first_daughter_, index_;
  std::vector<char> is_mother_;
};

void put_int(std::string& out, int64_t value) {
  char buffer[24];
  out.append(buffer, std::to_chars(buffer, buffer + sizeof buffer, value).ptr);
}

// One number as WriterAscii's " %.<precision>e" prints it.
void put_real(std::string& out, double value, int precision) {
  char buffer[64];
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
  put_int(out, static_cast<int64_t>(n));
  out += "\nU GEV MM\n";
  int written = 0;  // vertices written so far, which are numbered in order
  for (std::size_t j = 0; j < n; ++j) {
    const int64_t row = event.rows[j];
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
    put_int(out, static_cast<int64_t>(j + 1));
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

template <typename T>
using Array = py::array_t<T, py::array::c_style>;

template <typename Real>
Chunk<Real> chunk_of(const Array<int64_t>& counts, const Array<int64_t>& numbers,
                     const Array<int32_t>& pid, const Array<int32_t>& status,
                     const Array<int32_t>& m1, const Array<bool>& final, const Array<Real>& px,
                     const Array<Real>& py, const Array<Real>& pz, const Array<Real>& e,
                     const Array<Real>& mass, const Array<Real>& x, const Array<Real>& y,
                     const Array<Real>& z, const Array<Real>& t) {
  if (counts.ndim() != 1 || numbers.ndim() != 1 || counts.size() != numbers.size())
    throw std::invalid_argument("counts and numbers must be 1D and of one length");
  int64_t n_particles = 0;
  for (py::ssize_t k = 0; k < counts.size(); ++k) {
    if (counts.data()[k] < 0) throw std::invalid_argument("counts must not be negative");
    n_particles += counts.data()[k];
  }
  for (const py::array* column : std::initializer_list<const py::array*>{
           &pid, &status, &m1, &final, &px, &py, &pz, &e, &mass, &x, &y, &z, &t}) {
    if (column->ndim() != 1 || column->size() != n_particles)
      throw std::invalid_argument("every particle column must be 1D and hold sum(counts) values");
  }
  return {counts.size(), counts.data(), numbers.data(), pid.data(), status.data(), m1.data(),
          final.data(),  px.data(),     py.data(),      pz.data(),  e.data(),      mass.data(),
          x.data(),      y.data(),      z.data(),       t.data()};
}

// The text of the chunk's events up to the first refused one, the number of
// events in it, and the refusal ("" if none).
template <typename Real>
py::tuple format_events(const Array<int64_t>& counts, const Array<int64_t>& numbers,
                        const Array<int32_t>& pid, const Array<int32_t>& status,
                        const Array<int32_t>& m1, const Array<bool>& final, const Array<Real>& px,
                        const Array<Real>& py, const Array<Real>& pz, const Array<Real>& e,
                        const Array<Real>& mass, const Array<Real>& x, const Array<Real>& y,
                        const Array<Real>& z, const Array<Real>& t, int precision) {
  const Chunk<Real> c =
      chunk_of(counts, numbers, pid, status, m1, final, px, py, pz, e, mass, x, y, z, t);
  std::string text, error;
  text.reserve(static_cast<std::size_t>(pid.size()) * 112);
  py::ssize_t k = 0;
  {
    py::gil_scoped_release release;
    Builder<Real> builder(c);
    Event event;
    std::vector<int> vertex_of;
    for (int64_t base = 0; k < c.n_events; base += c.counts[k], ++k) {
      if (!builder.build(k, base, event, error)) break;
      format_event(c, event, precision, vertex_of, text);
    }
  }
  return py::make_tuple(py::bytes(text), k, error);
}

// The HEPEVT arrays of the chunk's events up to the first refused one, flat
// over those events, with each event's particle count, and the refusal.
template <typename Real>
py::dict hepevt_events(const Array<int64_t>& counts, const Array<int64_t>& numbers,
                       const Array<int32_t>& pid, const Array<int32_t>& status,
                       const Array<int32_t>& m1, const Array<bool>& final, const Array<Real>& px,
                       const Array<Real>& py, const Array<Real>& pz, const Array<Real>& e,
                       const Array<Real>& mass, const Array<Real>& x, const Array<Real>& y,
                       const Array<Real>& z, const Array<Real>& t) {
  const Chunk<Real> c =
      chunk_of(counts, numbers, pid, status, m1, final, px, py, pz, e, mass, x, y, z, t);
  Builder<Real> builder(c);
  Event event;
  std::string error;
  std::vector<int64_t> sizes;
  std::vector<int32_t> out_pid, out_status;
  std::vector<int64_t> parents;
  std::vector<double> momenta[5], vertices[4];
  const Real* const momentum_columns[5] = {c.px, c.py, c.pz, c.e, c.mass};
  const Real* const position_columns[4] = {c.x, c.y, c.z, c.t};
  py::ssize_t k = 0;
  for (int64_t base = 0; k < c.n_events; base += c.counts[k], ++k) {
    if (!builder.build(k, base, event, error)) break;
    sizes.push_back(static_cast<int64_t>(event.rows.size()));
    for (std::size_t j = 0; j < event.rows.size(); ++j) {
      const int64_t row = event.rows[j];
      const int source = event.source[j];
      out_pid.push_back(c.pid[row]);
      out_status.push_back(source != kBeam && c.final[row] ? kFinalStatus : c.status[row]);
      for (int q = 0; q < 5; ++q) momenta[q].push_back(momentum_columns[q][row]);
      const bool from_mother = source >= 0;
      for (int q = 0; q < 4; ++q)
        vertices[q].push_back(from_mother ? static_cast<double>(position_columns[q][row]) : 0.0);
      const int64_t first = source == kBeam ? -1 : source == kFromBeams ? 0 : source;
      const int64_t last = source == kBeam ? -1 : source == kFromBeams ? 1 : source;
      parents.push_back(first);
      parents.push_back(last);
    }
  }
  const auto array = [](const auto& values) {
    using T = typename std::decay_t<decltype(values)>::value_type;
    return py::array_t<T>(static_cast<py::ssize_t>(values.size()), values.data());
  };
  py::array_t<int64_t> parent_pairs({static_cast<py::ssize_t>(parents.size() / 2), py::ssize_t{2}});
  std::copy(parents.begin(), parents.end(), parent_pairs.mutable_data());
  py::dict out;
  out["counts"] = array(sizes);
  out["pid"] = array(out_pid);
  out["status"] = array(out_status);
  out["px"] = array(momenta[0]);
  out["py"] = array(momenta[1]);
  out["pz"] = array(momenta[2]);
  out["e"] = array(momenta[3]);
  out["m"] = array(momenta[4]);
  out["parents"] = parent_pairs;
  out["vx"] = array(vertices[0]);
  out["vy"] = array(vertices[1]);
  out["vz"] = array(vertices[2]);
  out["vt"] = array(vertices[3]);
  out["n_events"] = k;
  out["error"] = error;
  return out;
}

template <typename Real>
void bind(py::module_& m) {
  m.def("format_events", &format_events<Real>, py::arg("counts").noconvert(),
        py::arg("numbers").noconvert(), py::arg("pid").noconvert(), py::arg("status").noconvert(),
        py::arg("m1").noconvert(), py::arg("final").noconvert(), py::arg("px").noconvert(),
        py::arg("py").noconvert(), py::arg("pz").noconvert(), py::arg("e").noconvert(),
        py::arg("mass").noconvert(), py::arg("x").noconvert(), py::arg("y").noconvert(),
        py::arg("z").noconvert(), py::arg("t").noconvert(), py::arg("precision"));
  m.def("hepevt_events", &hepevt_events<Real>, py::arg("counts").noconvert(),
        py::arg("numbers").noconvert(), py::arg("pid").noconvert(), py::arg("status").noconvert(),
        py::arg("m1").noconvert(), py::arg("final").noconvert(), py::arg("px").noconvert(),
        py::arg("py").noconvert(), py::arg("pz").noconvert(), py::arg("e").noconvert(),
        py::arg("mass").noconvert(), py::arg("x").noconvert(), py::arg("y").noconvert(),
        py::arg("z").noconvert(), py::arg("t").noconvert());
}

}  // namespace

PYBIND11_MODULE(_hepmc_ascii, m) {
  m.doc() = "Parnassus's input in HepMC3's ASCII format, built and written in C++.";
  bind<float>(m);
  bind<double>(m);
}
