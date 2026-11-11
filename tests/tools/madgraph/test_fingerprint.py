import gzip
from pathlib import Path

import pytest

from omphjc.tools.madgraph.fingerprint import lhe_fingerprint

# An event file with the blocks MadGraph 3.8.1 writes after MadSpin.
LHE = """\
<LesHouchesEvents version="3.0">
<header>
<!--
{comment}
-->
<MGVersion>
3.8.1
</MGVersion>
<MG5ProcCard>
<![CDATA[
{proc_card}
]]>
</MG5ProcCard>
<MGRunCard>
<![CDATA[
{run_card}
]]>
</MGRunCard>
<slha>
{param_card}
</slha>
<MGGenerationInfo>
#  Number of Events        :       1
#  Integrated weight (pb)  :       1.052824299417
</MGGenerationInfo>
<madspin>
<![CDATA[
{madspin_card}
]]>
</madspin>
</header>
<init>
2212 2212 6.500000e+03 6.500000e+03 0 0 247000 247000 -4 1
 1.052824299417e+00 2.398374998897e-03 1.052824299417e+00 1
<generator name='MadGraph5_aMC@NLO' version='3.8.1'>please cite 1405.0301 </generator>
</init>
{events}</LesHouchesEvents>
"""
CARDS = {
    "proc_card": "import model sm\ngenerate p p > t t~\noutput TTBar",
    "run_card": "  42\t= iseed ! random seed\n  20.0\t= ptj ! minimum jet pt",
    "param_card": "BLOCK MASS\n    6 1.725000e+02 # MT\nDECAY   6 1.491500e+00 # WT",
    "madspin_card": (
        "set max_weight_ps_point 400\n"
        "decay t > w+ b, w+ > j j\n"
        "decay t~ > w- b~, w- > j j\n"
        "launch"
    ),
}
EVENTS = "<event>\n 21 -1 0 0 501 502 0.0 0.0 +1.0e+02 1.0e+02 0.0\n</event>\n"


def _write(
    path: Path, *, events: str = EVENTS, comment: str = "", **cards: str
) -> Path:
    text = LHE.format(comment=comment, events=events, **{**CARDS, **cards})
    with gzip.open(path, "wt") if path.suffix == ".gz" else path.open("w") as stream:
        stream.write(text)
    return path


def test_an_lhe_fingerprint_names_its_scheme(tmp_path: Path) -> None:
    assert lhe_fingerprint(_write(tmp_path / "events.lhe")).startswith("lhe-v1:")


def test_the_gzipped_and_plain_forms_of_a_file_have_one_fingerprint(
    tmp_path: Path,
) -> None:
    plain = _write(tmp_path / "events.lhe")
    compressed = _write(tmp_path / "events.lhe.gz")
    assert plain.read_bytes() != compressed.read_bytes()
    assert lhe_fingerprint(plain) == lhe_fingerprint(compressed)


def test_header_comments_do_not_count(tmp_path: Path) -> None:
    reference = _write(tmp_path / "reference.lhe")
    commented = _write(
        tmp_path / "commented.lhe",
        comment="written at another time",
        proc_card="# a comment line\n" + CARDS["proc_card"],
        run_card=CARDS["run_card"].replace("random seed", "another comment"),
        param_card=CARDS["param_card"].replace("# WT", "# top width"),
        madspin_card=CARDS["madspin_card"].replace("400", "400  # points"),
    )
    assert lhe_fingerprint(commented) == lhe_fingerprint(reference)


def test_the_directories_of_the_model_and_output_paths_do_not_count(
    tmp_path: Path,
) -> None:
    located = (
        "import model /scratch/job_1/models/sm/\n"
        "generate p p > t t~\n"
        "output /scratch/job_1/generate/TTBar"
    )
    reference = _write(tmp_path / "reference.lhe")
    moved = _write(tmp_path / "moved.lhe", proc_card=located)
    other = _write(tmp_path / "other.lhe", proc_card=located.replace("sm/", "heft/"))
    assert lhe_fingerprint(moved) == lhe_fingerprint(reference)
    assert lhe_fingerprint(other) != lhe_fingerprint(reference)


def test_the_parameter_and_madspin_cards_count_as_parsed(tmp_path: Path) -> None:
    reference = _write(tmp_path / "reference.lhe")
    options, top, antitop, launch = CARDS["madspin_card"].splitlines()
    rewritten = _write(
        tmp_path / "rewritten.lhe",
        param_card="decay 6 1.4915\nblock mass\n  6 172.5",
        madspin_card="\n".join([options, antitop, top, launch]),
    )
    wider = _write(
        tmp_path / "wider.lhe",
        param_card=CARDS["param_card"].replace("1.491500e+00", "1.6"),
    )
    assert lhe_fingerprint(rewritten) == lhe_fingerprint(reference)
    assert lhe_fingerprint(wider) != lhe_fingerprint(reference)


def test_a_run_card_value_or_one_event_changes_the_fingerprint(tmp_path: Path) -> None:
    reference = lhe_fingerprint(_write(tmp_path / "reference.lhe"))
    other_cut = _write(
        tmp_path / "cut.lhe", run_card=CARDS["run_card"].replace("20.0", "30.0")
    )
    other_event = _write(
        tmp_path / "event.lhe", events=EVENTS.replace("+1.0e+02", "+1.1e+02")
    )
    assert lhe_fingerprint(other_cut) != reference
    assert lhe_fingerprint(other_event) != reference


def test_a_file_without_an_init_block_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "events.lhe"
    path.write_text("<LesHouchesEvents>\n<event>\n</event>\n")
    with pytest.raises(ValueError, match="it has no <init> block"):
        lhe_fingerprint(path)


@pytest.mark.parametrize(
    "last_text_kept",
    [
        pytest.param("<init>\n2212 2212", id="inside the init block"),
        pytest.param("</init>\n", id="before the first event"),
        pytest.param("<event>\n 21 -1", id="inside an event"),
        pytest.param("</event>\n", id="before the closing line"),
        pytest.param("</LesHouchesEvents>", id="inside the closing line"),
    ],
)
def test_a_file_cut_short_is_refused(tmp_path: Path, last_text_kept: str) -> None:
    text = _write(tmp_path / "complete.lhe").read_text()
    path = tmp_path / "cut.lhe"
    path.write_text(text[: text.index(last_text_kept) + len(last_text_kept)])
    with pytest.raises(ValueError, match="is not a complete LHE file"):
        lhe_fingerprint(path)


def test_a_gzip_file_cut_short_is_refused(tmp_path: Path) -> None:
    complete = _write(tmp_path / "complete.lhe.gz").read_bytes()
    path = tmp_path / "cut.lhe.gz"
    path.write_bytes(complete[: len(complete) // 2])
    with pytest.raises(ValueError, match="is not a complete gzip file"):
        lhe_fingerprint(path)


def test_a_gz_file_that_is_not_gzip_data_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "events.lhe.gz"
    path.write_bytes(_write(tmp_path / "events.lhe").read_bytes())
    with pytest.raises(ValueError, match="is not a complete gzip file"):
        lhe_fingerprint(path)
