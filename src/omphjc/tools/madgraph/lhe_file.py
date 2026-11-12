"""An LHE event file written by MadGraph.

An LHE file (Les Houches Event File, https://arxiv.org/abs/hep-ph/0609017) has
three parts. The header holds the cards MadGraph ran with. The ``<init>``
block holds the beams, the cross sections and the name and version of the
generator. The events come last. An event holds its particles and the values
MadGraph stores with them for matching and reweighting.

An event file is too large to keep in memory. :class:`LHEFile` holds the
header and the ``<init>`` block as a :class:`Banner`, and one hash of every
byte from the ``<init>`` line to the end of the file.

Two files have the same fingerprint when they hold the same events and were
made with the same cards. Differences that do not change the sample are
ignored: the time the file was compressed, the comments in its header, and the
directory MadGraph ran in.

Only a complete file is read. MadGraph writes the line
``</LesHouchesEvents>`` last, so a file that does not end with that line was
cut short, and it is refused.
"""

import gzip
import hashlib
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from omphjc.data_files import DataFile
from omphjc.tools.madgraph.banner import Banner
from omphjc.tools.madgraph.madspin_card import MadSpinCard
from omphjc.tools.madgraph.proc_card import ProcCard
from omphjc.tools.madgraph.slha_card import SLHACard

# The last line of an LHE file. MadGraph writes it after the last event of an
# unweighted file (EventFile.unweight,
# https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/madgraph/various/lhe_parser.py#L1077-L1095)
# and MadSpin after the last decayed event
# (https://github.com/mg5amcnlo/mg5amcnlo/blob/v3.8.1/MadSpin/decay.py#L2601).
_LAST_LINE = b"</LesHouchesEvents>\n"

# Number of bytes read at a time while hashing the events.
_READ_BYTES = 1 << 20


@dataclass(frozen=True)
class LHEFile(DataFile):
    """The content of an LHE file written by MadGraph.

    Parameters
    ----------
    banner : Banner
        What the header and the ``<init>`` block record about the sample. It
        equals the result of :meth:`Banner.read` on the same file.
    events_sha256 : str
        The SHA-256 hash, in hexadecimal, of every byte from the ``<init>``
        line to the end of the file. That part holds the ``<init>`` block and
        the events.
    """

    record_scheme: ClassVar[str] = "lhe-v1"

    banner: Banner
    events_sha256: str

    @classmethod
    def read(cls, path: Path) -> "LHEFile":
        """Return the content of the LHE file at `path`.

        The whole file is read once. A name that ends in ``.gz`` is read as a
        gzip-compressed file.

        Raises
        ------
        ValueError
            If the file has no ``<init>`` block, if it does not end with the
            line ``</LesHouchesEvents>``, if its gzip data is cut short or
            damaged, or if its header is missing a part that MadGraph always
            writes (see :meth:`Banner.from_text`).
        """
        banner_lines = []
        events = hashlib.sha256()
        has_init = False
        ending = b""
        try:
            with gzip.open(path) if path.suffix == ".gz" else path.open("rb") as stream:
                for line in stream:
                    has_init = has_init or line.startswith(b"<init>")
                    if has_init:
                        events.update(line)
                    banner_lines.append(line)
                    ending = line
                    if line.startswith((b"</init>", b"<event>")):
                        break
                if not has_init:
                    raise ValueError(
                        f"{path} is not an LHE file: it has no <init> block"
                    )
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
        banner_text = b"".join(banner_lines).decode("utf-8", errors="replace")
        return cls(
            banner=Banner.from_text(banner_text), events_sha256=events.hexdigest()
        )

    def content_record(self) -> dict[str, Any]:
        """Return the content of the cards and the hash of the events.

        Each card is written down with its own content record, so its layout
        and its comments do not count. A card that the header lacks is
        written down as an empty card.
        """
        banner = self.banner
        proc_card = banner.proc_card or ProcCard.from_text("")
        param_card = banner.param_card or SLHACard.from_text("")
        madspin = (banner.madspin_card or MadSpinCard.from_text("")).content_record()
        return {
            "run_card": banner.run_card.content_record(),
            "proc_card": proc_card.content_record(),
            "param_card": param_card.content_record(),
            "madspin_options": madspin["options"],
            "madspin_decays": madspin["decays"],
            "events": self.events_sha256,
        }
