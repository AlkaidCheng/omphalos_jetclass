"""The banner MadGraph writes at the top of its event files.

The banner is the ``<header>`` of an LHE file: the MadGraph version, the
process and run cards as used, the parameter card, the generation summary
(event count and integrated cross section) and, after MadSpin, the MadSpin
card. The event file continues with the ``<init>`` block, which carries the
cross section and its statistical error per subprocess. MadGraph also stores
the header alone as ``run_<n>_tag_<m>_banner.txt``.
"""

import gzip
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import IO, overload

from omphjc.madgraph.runcard import parse_run_card
from omphjc.processes.catalogue import RunCardValue

# Blocks of the banner, captured without their tags.
_GENERATION_INFO_BLOCK_PATTERN = re.compile(
    r"<MGGenerationInfo>(.*?)</MGGenerationInfo>", re.S
)
_VERSION_BLOCK_PATTERN = re.compile(r"<MGVersion>(.*?)</MGVersion>", re.S)
_RUN_CARD_BLOCK_PATTERN = re.compile(r"<MGRunCard>(.*?)</MGRunCard>", re.S)
_INIT_BLOCK_PATTERN = re.compile(r"<init>(.*?)</init>", re.S)

# Values of the generation summary.
_N_EVENTS_PATTERN = re.compile(r"#\s*Number of Events\s*:\s*(\d+)")
_CROSS_SECTION_PATTERN = re.compile(
    r"#\s*Integrated weight \(pb\)\s*:\s*([-+0-9.eEdD]+)"
)

# Layout of the <init> block (Les Houches Event File accord, section 2.1,
# https://arxiv.org/abs/hep-ph/0609017): one beam line
# "IDBMUP(2) EBMUP(2) PDFGUP(2) PDFSUP(2) IDWTUP NPRUP", then NPRUP lines
# "XSECUP XERRUP XMAXUP LPRUP".
_INIT_HEADER_FIELDS = 10
_NPRUP_FIELD = 9  # number of subprocess lines
_SUBPROCESS_FIELDS = 4
_XERRUP_FIELD = 1  # cross-section error, pb


@dataclass(frozen=True)
class Banner:
    """What MadGraph recorded about one event sample.

    Parameters
    ----------
    version : str
        MadGraph5_aMC@NLO version that produced the sample.
    n_events : int
        Number of unweighted events written.
    cross_section_pb : float
        Integrated cross section in pb, from the generation summary.
    cross_section_error_pb : float or None
        Statistical error in pb, summed in quadrature over the subprocesses
        of the ``<init>`` block; ``None`` when the text has no such block.
    run_card : dict[str, RunCardValue]
        The run card as MadGraph used it.
    madspin : bool
        Whether MadSpin decayed the events.
    """

    version: str
    n_events: int
    cross_section_pb: float
    cross_section_error_pb: float | None
    run_card: dict[str, RunCardValue]
    madspin: bool

    @property
    def seed(self) -> int:
        """The ``iseed`` MadGraph ran with."""
        value = self.run_card.get("iseed")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"The run card holds no integer iseed: {value!r}")
        return value

    @classmethod
    def read(cls, path: Path) -> "Banner":
        """Read the banner of an LHE file (plain or gzipped) or of a banner file.

        Reading stops at the end of the ``<init>`` block or at the first event,
        so the size of the event file does not matter.
        """
        lines: list[str] = []
        with _open_text(path) as stream:
            for line in stream:
                lines.append(line)
                if line.startswith("</init>") or line.startswith("<event>"):
                    break
        return cls.from_text("".join(lines))

    @classmethod
    def from_text(cls, text: str) -> "Banner":
        """Return the banner recorded in `text`.

        Raises
        ------
        ValueError
            If `text` lacks the generation summary, its event count or weight,
            the version or the run card.
        """
        summary = _capture(
            _GENERATION_INFO_BLOCK_PATTERN, text, missing="MGGenerationInfo block"
        )
        init = _capture(_INIT_BLOCK_PATTERN, text)
        return cls(
            version=_capture(
                _VERSION_BLOCK_PATTERN, text, missing="MGVersion block"
            ).strip(),
            n_events=int(_capture(_N_EVENTS_PATTERN, summary, missing="event count")),
            cross_section_pb=_fortran_float(
                _capture(_CROSS_SECTION_PATTERN, summary, missing="integrated weight")
            ),
            cross_section_error_pb=None if init is None else _init_error(init),
            run_card=parse_run_card(
                _capture(_RUN_CARD_BLOCK_PATTERN, text, missing="MGRunCard block")
            ),
            madspin="<madspin>" in text,
        )


def _open_text(path: Path) -> IO[str]:
    """Open a banner source for reading as text.

    MadGraph gzips the event file it writes (``Events/run_01/
    unweighted_events.lhe.gz``, or ``run_01_decayed_1/`` after MadSpin), so
    that is the usual input. The two plain-text forms are the header MadGraph
    stores alongside it (``run_01_tag_1_banner.txt``) and the uncompressed
    ``.lhe`` a job keeps for ``DelphesPythia8``, which reads the event file as
    text.
    """
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open(encoding="utf-8", errors="replace")


@overload
def _capture(pattern: re.Pattern[str], text: str, *, missing: str) -> str: ...


@overload
def _capture(pattern: re.Pattern[str], text: str) -> str | None: ...


def _capture(
    pattern: re.Pattern[str], text: str, *, missing: str | None = None
) -> str | None:
    """Return the first group of `pattern` in `text`.

    Without a match the result is ``None``, or a ``ValueError`` naming the
    `missing` part when the caller requires it.
    """
    match = pattern.search(text)
    if match is not None:
        return match.group(1)
    if missing is None:
        return None
    raise ValueError(f"Not a MadGraph banner: no {missing}")


def _init_error(block: str) -> float:
    """Return the cross-section error of an ``<init>`` block, in pb.

    The block follows the Les Houches Event File accord: one line describing
    the beams, ending with NPRUP, the number of subprocesses, then one line
    per subprocess with ``XSECUP XERRUP XMAXUP LPRUP``; MadGraph appends a
    ``<generator>`` tag line, which is skipped. The errors of the subprocesses
    are summed in quadrature. A MadGraph block with one subprocess::

        2212 2212 6.500000e+03 6.500000e+03 0 0 247000 247000 -4 1
         1.052824299417E+00 2.398374998897E-03 1.052824299417E+00 1
        <generator name='MadGraph5_aMC@NLO' version='3.5.7'>please cite 1405.0301 </generator>

    Raises
    ------
    ValueError
        If the block does not have this shape.
    """
    rows = [
        line.split()
        for line in block.strip().splitlines()
        if line.strip() and not line.lstrip().startswith("<")
    ]
    if not rows or len(rows[0]) < _INIT_HEADER_FIELDS:
        raise ValueError("The <init> block does not start with a beam line")
    n_subprocesses = int(rows[0][_NPRUP_FIELD])
    subprocesses = rows[1 : 1 + n_subprocesses]
    if n_subprocesses < 1 or len(subprocesses) < n_subprocesses:
        raise ValueError(
            f"The <init> block announces {n_subprocesses} subprocess lines "
            f"but holds {len(subprocesses)}"
        )
    if any(len(row) < _SUBPROCESS_FIELDS for row in subprocesses):
        raise ValueError("A subprocess line of the <init> block is incomplete")
    errors = (_fortran_float(row[_XERRUP_FIELD]) for row in subprocesses)
    return math.sqrt(sum(error**2 for error in errors))


def _fortran_float(text: str) -> float:
    return float(text.replace("d", "e").replace("D", "e"))
