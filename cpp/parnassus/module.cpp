// The Python module omphjc.tools.parnassus._hepmc_ascii: NumPy arrays in,
// bytes and arrays out, around the functions of hepmc_ascii.hpp.
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <stdexcept>
#include <vector>

#include "parnassus/hepmc_ascii.hpp"

namespace py = pybind11;
namespace parnassus = omphjc::parnassus;

namespace {

template <typename T>
using Array = py::array_t<T, py::array::c_style>;

// The chunk the arrays hold, once they are one-dimensional and every particle
// column holds sum(counts) values.
template <typename Real>
parnassus::Chunk<Real> chunk_of(const Array<std::int64_t>& counts,
                                const Array<std::int64_t>& numbers,
                                const Array<std::int32_t>& pid, const Array<std::int32_t>& status,
                                const Array<std::int32_t>& m1, const Array<bool>& final,
                                const Array<Real>& px, const Array<Real>& py,
                                const Array<Real>& pz, const Array<Real>& e,
                                const Array<Real>& mass, const Array<Real>& x,
                                const Array<Real>& y, const Array<Real>& z,
                                const Array<Real>& t) {
  if (counts.ndim() != 1 || numbers.ndim() != 1 || counts.size() != numbers.size())
    throw std::invalid_argument("counts and numbers must be 1D and of one length");
  std::int64_t n_particles = 0;
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

// The text of the chunk's events up to the first refused one, as bytes, the
// number of events in it, and the refusal ("" if none).
template <typename Real>
py::tuple format_events(const Array<std::int64_t>& counts, const Array<std::int64_t>& numbers,
                        const Array<std::int32_t>& pid, const Array<std::int32_t>& status,
                        const Array<std::int32_t>& m1, const Array<bool>& final,
                        const Array<Real>& px, const Array<Real>& py, const Array<Real>& pz,
                        const Array<Real>& e, const Array<Real>& mass, const Array<Real>& x,
                        const Array<Real>& y, const Array<Real>& z, const Array<Real>& t,
                        int precision, int threads) {
  const auto chunk =
      chunk_of(counts, numbers, pid, status, m1, final, px, py, pz, e, mass, x, y, z, t);
  parnassus::Text text;
  {
    py::gil_scoped_release release;
    text = parnassus::format_events(chunk, precision, threads);
  }
  std::size_t size = 0;
  for (const auto& piece : text.pieces) size += piece.size();
  PyObject* bytes = PyBytes_FromStringAndSize(nullptr, static_cast<py::ssize_t>(size));
  if (!bytes) throw py::error_already_set();
  char* out = PyBytes_AS_STRING(bytes);
  for (const auto& piece : text.pieces) {
    std::memcpy(out, piece.data(), piece.size());
    out += piece.size();
  }
  return py::make_tuple(py::reinterpret_steal<py::bytes>(bytes), text.n_events, text.error);
}

template <typename T>
py::array_t<T> array_of(const std::vector<T>& values) {
  return py::array_t<T>(static_cast<py::ssize_t>(values.size()), values.data());
}

// The HEPEVT arrays of the chunk's events up to the first refused one, flat
// over those events, with each event's particle count, and the refusal.
template <typename Real>
py::dict hepevt_events(const Array<std::int64_t>& counts, const Array<std::int64_t>& numbers,
                       const Array<std::int32_t>& pid, const Array<std::int32_t>& status,
                       const Array<std::int32_t>& m1, const Array<bool>& final,
                       const Array<Real>& px, const Array<Real>& py, const Array<Real>& pz,
                       const Array<Real>& e, const Array<Real>& mass, const Array<Real>& x,
                       const Array<Real>& y, const Array<Real>& z, const Array<Real>& t) {
  const auto chunk =
      chunk_of(counts, numbers, pid, status, m1, final, px, py, pz, e, mass, x, y, z, t);
  parnassus::Hepevt hepevt;
  {
    py::gil_scoped_release release;
    hepevt = parnassus::hepevt_events(chunk);
  }
  py::array_t<std::int64_t> parents(
      {static_cast<py::ssize_t>(hepevt.parents.size() / 2), py::ssize_t{2}});
  std::copy(hepevt.parents.begin(), hepevt.parents.end(), parents.mutable_data());
  py::dict out;
  out["counts"] = array_of(hepevt.counts);
  out["pid"] = array_of(hepevt.pid);
  out["status"] = array_of(hepevt.status);
  out["px"] = array_of(hepevt.px);
  out["py"] = array_of(hepevt.py);
  out["pz"] = array_of(hepevt.pz);
  out["e"] = array_of(hepevt.e);
  out["m"] = array_of(hepevt.m);
  out["parents"] = parents;
  out["vx"] = array_of(hepevt.vx);
  out["vy"] = array_of(hepevt.vy);
  out["vz"] = array_of(hepevt.vz);
  out["vt"] = array_of(hepevt.vt);
  out["n_events"] = hepevt.n_events;
  out["error"] = hepevt.error;
  return out;
}

template <typename Real>
void bind(py::module_& m) {
  m.def("format_events", &format_events<Real>, py::arg("counts").noconvert(),
        py::arg("numbers").noconvert(), py::arg("pid").noconvert(), py::arg("status").noconvert(),
        py::arg("m1").noconvert(), py::arg("final").noconvert(), py::arg("px").noconvert(),
        py::arg("py").noconvert(), py::arg("pz").noconvert(), py::arg("e").noconvert(),
        py::arg("mass").noconvert(), py::arg("x").noconvert(), py::arg("y").noconvert(),
        py::arg("z").noconvert(), py::arg("t").noconvert(), py::arg("precision"),
        py::arg("threads") = 1);
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
