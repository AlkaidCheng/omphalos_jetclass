// The Python module omphjc.tools.parnassus._hepmc_ascii: NumPy arrays in,
// bytes and arrays out, around the functions of hepmc_ascii.hpp.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <stdexcept>
#include <vector>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include "parnassus/hepmc_ascii.hpp"

namespace parnassus = omphjc::parnassus;

namespace {

template <typename T>
using Array = pybind11::array_t<T, pybind11::array::c_style>;

// The chunk the arrays hold, once they are one-dimensional and every particle
// column holds sum(particle_counts) values.
template <typename Real>
[[nodiscard]] parnassus::Chunk<Real> to_chunk(
    const Array<std::int64_t>& particle_counts, const Array<std::int64_t>& event_numbers,
    const Array<std::int32_t>& pid, const Array<std::int32_t>& status,
    const Array<std::int32_t>& mother, const Array<bool>& is_final, const Array<Real>& px,
    const Array<Real>& py, const Array<Real>& pz, const Array<Real>& e, const Array<Real>& mass,
    const Array<Real>& x, const Array<Real>& y, const Array<Real>& z, const Array<Real>& t) {
  if (particle_counts.ndim() != 1 || event_numbers.ndim() != 1 ||
      particle_counts.size() != event_numbers.size()) {
    throw std::invalid_argument("particle_counts and event_numbers must be 1D and of one length");
  }
  std::int64_t n_particles = 0;
  for (pybind11::ssize_t k = 0; k < particle_counts.size(); ++k) {
    if (particle_counts.data()[k] < 0) {
      throw std::invalid_argument("particle_counts must not be negative");
    }
    n_particles += particle_counts.data()[k];
  }
  for (const pybind11::array* column : std::initializer_list<const pybind11::array*>{
           &pid, &status, &mother, &is_final, &px, &py, &pz, &e, &mass, &x, &y, &z, &t}) {
    if (column->ndim() != 1 || column->size() != n_particles) {
      throw std::invalid_argument(
          "every particle column must be 1D and hold sum(particle_counts) values");
    }
  }
  return {particle_counts.size(),
          particle_counts.data(),
          event_numbers.data(),
          pid.data(),
          status.data(),
          mother.data(),
          is_final.data(),
          px.data(),
          py.data(),
          pz.data(),
          e.data(),
          mass.data(),
          x.data(),
          y.data(),
          z.data(),
          t.data()};
}

// The text of the chunk's events up to the first refused one, as bytes, the
// number of events in it, and the refusal ("" if none).
template <typename Real>
[[nodiscard]] pybind11::tuple format_events(
    const Array<std::int64_t>& particle_counts, const Array<std::int64_t>& event_numbers,
    const Array<std::int32_t>& pid, const Array<std::int32_t>& status,
    const Array<std::int32_t>& mother, const Array<bool>& is_final, const Array<Real>& px,
    const Array<Real>& py, const Array<Real>& pz, const Array<Real>& e, const Array<Real>& mass,
    const Array<Real>& x, const Array<Real>& y, const Array<Real>& z, const Array<Real>& t,
    int precision, int thread_count) {
  const auto chunk = to_chunk(particle_counts, event_numbers, pid, status, mother, is_final, px, py,
                              pz, e, mass, x, y, z, t);
  parnassus::EventText text;
  {
    pybind11::gil_scoped_release release;
    text = parnassus::format_events(chunk, precision, thread_count);
  }
  std::size_t size = 0;
  for (const auto& piece : text.pieces) {
    size += piece.size();
  }
  PyObject* bytes = PyBytes_FromStringAndSize(nullptr, static_cast<pybind11::ssize_t>(size));
  if (!bytes) {
    throw pybind11::error_already_set();
  }
  char* out = PyBytes_AS_STRING(bytes);
  for (const auto& piece : text.pieces) {
    std::memcpy(out, piece.data(), piece.size());
    out += piece.size();
  }
  return pybind11::make_tuple(pybind11::reinterpret_steal<pybind11::bytes>(bytes), text.n_events,
                              text.error);
}

template <typename T>
[[nodiscard]] pybind11::array_t<T> copy_to_array(const std::vector<T>& values) {
  return pybind11::array_t<T>(static_cast<pybind11::ssize_t>(values.size()), values.data());
}

// The HEPEVT arrays of the chunk's events up to the first refused one, flat
// over those events, with each event's particle count, and the refusal.
template <typename Real>
[[nodiscard]] pybind11::dict to_hepevt(
    const Array<std::int64_t>& particle_counts, const Array<std::int64_t>& event_numbers,
    const Array<std::int32_t>& pid, const Array<std::int32_t>& status,
    const Array<std::int32_t>& mother, const Array<bool>& is_final, const Array<Real>& px,
    const Array<Real>& py, const Array<Real>& pz, const Array<Real>& e, const Array<Real>& mass,
    const Array<Real>& x, const Array<Real>& y, const Array<Real>& z, const Array<Real>& t) {
  const auto chunk = to_chunk(particle_counts, event_numbers, pid, status, mother, is_final, px, py,
                              pz, e, mass, x, y, z, t);
  parnassus::HepevtArrays arrays;
  {
    pybind11::gil_scoped_release release;
    arrays = parnassus::to_hepevt(chunk);
  }
  pybind11::array_t<std::int64_t> parents(
      {static_cast<pybind11::ssize_t>(arrays.parents.size() / 2), pybind11::ssize_t{2}});
  std::copy(arrays.parents.begin(), arrays.parents.end(), parents.mutable_data());
  pybind11::dict out;
  out["particle_counts"] = copy_to_array(arrays.particle_counts);
  out["pid"] = copy_to_array(arrays.pid);
  out["status"] = copy_to_array(arrays.status);
  out["px"] = copy_to_array(arrays.px);
  out["py"] = copy_to_array(arrays.py);
  out["pz"] = copy_to_array(arrays.pz);
  out["e"] = copy_to_array(arrays.e);
  out["m"] = copy_to_array(arrays.m);
  out["parents"] = parents;
  out["vx"] = copy_to_array(arrays.vx);
  out["vy"] = copy_to_array(arrays.vy);
  out["vz"] = copy_to_array(arrays.vz);
  out["vt"] = copy_to_array(arrays.vt);
  out["n_events"] = arrays.n_events;
  out["error"] = arrays.error;
  return out;
}

template <typename Real>
void bind_functions(pybind11::module_& m) {
  using namespace pybind11::literals;
  m.def("format_events", &format_events<Real>, "particle_counts"_a.noconvert(),
        "event_numbers"_a.noconvert(), "pid"_a.noconvert(), "status"_a.noconvert(),
        "mother"_a.noconvert(), "is_final"_a.noconvert(), "px"_a.noconvert(), "py"_a.noconvert(),
        "pz"_a.noconvert(), "e"_a.noconvert(), "mass"_a.noconvert(), "x"_a.noconvert(),
        "y"_a.noconvert(), "z"_a.noconvert(), "t"_a.noconvert(), "precision"_a, "threads"_a = 1);
  m.def("to_hepevt", &to_hepevt<Real>, "particle_counts"_a.noconvert(),
        "event_numbers"_a.noconvert(), "pid"_a.noconvert(), "status"_a.noconvert(),
        "mother"_a.noconvert(), "is_final"_a.noconvert(), "px"_a.noconvert(), "py"_a.noconvert(),
        "pz"_a.noconvert(), "e"_a.noconvert(), "mass"_a.noconvert(), "x"_a.noconvert(),
        "y"_a.noconvert(), "z"_a.noconvert(), "t"_a.noconvert());
}

}  // namespace

PYBIND11_MODULE(_hepmc_ascii, m) {
  m.doc() = "Parnassus's input in HepMC3's ASCII format, built and written in C++.";
  bind_functions<float>(m);
  bind_functions<double>(m);
}
