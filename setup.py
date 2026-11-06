"""Build omphjc's C++ extension; the package's metadata is in pyproject.toml."""

import os
import sys
import sysconfig

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

# The extension formats numbers with floating-point std::to_chars, which macOS's
# libc++ provides from macOS 13.3 on (below it, clang reports "is unavailable:
# introduced in macOS 13.3"). pybind11 sets no target of its own once
# MACOSX_DEPLOYMENT_TARGET is set. A wheel's tag keeps only the major version
# (macosx_13_0), so a wheel built for others needs a target of 14.0.
MACOS_MINIMUM = (13, 3)


def _raise_macos_target() -> None:
    target = os.environ.get("MACOSX_DEPLOYMENT_TARGET") or sysconfig.get_config_var(
        "MACOSX_DEPLOYMENT_TARGET"
    )
    version = tuple(int(part) for part in str(target or "0").split("."))
    if version < MACOS_MINIMUM:
        os.environ["MACOSX_DEPLOYMENT_TARGET"] = ".".join(map(str, MACOS_MINIMUM))


if sys.platform == "darwin":
    _raise_macos_target()

setup(
    ext_modules=[
        Pybind11Extension(
            "omphjc.tools.parnassus._hepmc_ascii",
            ["src/omphjc/tools/parnassus/_hepmc_ascii.cpp"],
            cxx_std=17,
        )
    ],
    cmdclass={"build_ext": build_ext},
)
