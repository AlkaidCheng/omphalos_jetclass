"""Fingerprint an LHE event file written by MadGraph.

A fingerprint is a short string that stands for the content of a file. Two LHE
files have the same fingerprint when they hold the same events and were made
with the same cards. Differences that do not change the sample are ignored:
the time the file was compressed, the comments in its header, and the
directory MadGraph ran in.

The fingerprint is built from two parts of the file:

- The cards in the header. Each card is parsed first, so only its content
  counts, not its layout or comments: the settings of the run card, the
  commands of the process card, the entries of the parameter card, and the
  options and decay chains of the MadSpin card.
- Everything from the ``<init>`` line to the end of the file. This part is
  hashed byte for byte. It holds the ``<init>`` block, with the beams, the
  cross sections and the name and version of the generator, and then the
  events. An event holds its particles and the values MadGraph stores with
  them for matching and reweighting.

Only a complete file has a fingerprint. MadGraph writes the line
``</LesHouchesEvents>`` last, so a file that does not end with that line was
cut short, and it is refused.
"""

import gzip
import hashlib
import json
import zlib
from pathlib import Path

from omphjc.tools.madgraph.banner import Banner
from omphjc.tools.madgraph.madspin import parse_madspin_card
from omphjc.tools.madgraph.proc_card import ProcCard
from omphjc.tools.madgraph.slha_card import SLHACard

LHE_SCHEME = "lhe-v1"
"""The label at the start of every fingerprint.

It gets a new value whenever the fingerprint is computed in a different way,
so that fingerprints made by two versions of the method never match.
"""

# The last line of an LHE file. MadGraph writes it after the last event of an
# unweighted file (EventFile.unweight,
# https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/various/lhe_parser.py#L1077-L1095)
# and MadSpin after the last decayed event
# (https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/MadSpin/decay.py#L2601).
_LAST_LINE = b"</LesHouchesEvents>\n"

# Number of bytes read at a time while hashing the events.
_READ_BYTES = 1 << 20


def lhe_fingerprint(path: Path) -> str:
    """Return the fingerprint of an LHE file.

    Parameters
    ----------
    path : Path
        The event file MadGraph wrote. A name that ends in ``.gz`` is read as
        a gzip-compressed file.

    Returns
    -------
    str
        The text ``lhe-v1:`` followed by a SHA-256 hash in hexadecimal.

    Raises
    ------
    ValueError
        If the file has no ``<init>`` block, if it does not end with the line
        ``</LesHouchesEvents>``, if its gzip data is cut short or damaged, or
        if its header is missing a part that MadGraph always writes (see
        :meth:`Banner.from_text`).
    """
    header = bytearray()
    events = hashlib.sha256()
    ending = b""
    try:
        with gzip.open(path) if path.suffix == ".gz" else path.open("rb") as stream:
            for line in stream:
                if line.startswith(b"<init>"):
                    events.update(line)
                    break
                header += line
            else:
                raise ValueError(f"{path} is not an LHE file: it has no <init> block")
            while block := stream.read(_READ_BYTES):
                events.update(block)
                ending = (ending + block)[-len(_LAST_LINE) :]
    except (EOFError, gzip.BadGzipFile, zlib.error) as error:
        raise ValueError(f"{path} is not a complete gzip file: {error}") from None
    if ending != _LAST_LINE:
        raise ValueError(
            f"{path} is not a complete LHE file: it does not end with the line "
            "</LesHouchesEvents>"
        )
    banner = Banner.from_text(header.decode("utf-8", errors="replace"))
    madspin = parse_madspin_card(banner.madspin_card or "")
    record = {
        "run_card": banner.run_card,
        "proc_card": ProcCard.from_text(banner.proc_card or "").content_record(),
        "param_card": SLHACard.from_text(banner.param_card or "").content_record(),
        "madspin_options": madspin.options,
        "madspin_decays": sorted(madspin.decays),
        "events": events.hexdigest(),
    }
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return f"{LHE_SCHEME}:{hashlib.sha256(canonical.encode()).hexdigest()}"
