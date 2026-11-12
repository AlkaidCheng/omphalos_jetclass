import gzip
import re
from pathlib import Path

import pytest

from omphjc.tools.madgraph.banner import Banner

BANNER = Path(__file__).parents[2] / "data" / "madgraph" / "TTBar_banner.txt"


def test_banner_of_a_decayed_sample() -> None:
    banner = Banner.read(BANNER)
    assert banner.version == "3.5.7"
    assert banner.n_events == 10000
    assert banner.cross_section_pb == pytest.approx(1.052824254921272)
    assert banner.cross_section_error_pb == pytest.approx(2.398374998897e-3)
    assert banner.seed == 42
    assert banner.run_card.settings["ebeam1"] == 6500.0
    assert banner.run_card.settings["pt_min_pdg"] == {6: 450.0}
    assert banner.uses_madspin is True


def test_banner_file_without_init_block_has_no_error() -> None:
    text = BANNER.read_text()
    text = re.sub(r"<madspin>.*?</madspin>\n", "", text, flags=re.S)
    text = re.sub(r"<init>.*?</init>\n", "", text, flags=re.S)
    banner = Banner.from_text(text)
    assert banner.cross_section_pb == pytest.approx(1.052824254921272)
    assert banner.cross_section_error_pb is None
    assert banner.uses_madspin is False


def test_cards_are_kept_without_their_tags_and_cdata_sections() -> None:
    banner = Banner.read(BANNER)
    assert (banner.proc_card, banner.param_card) == (None, None)
    assert banner.madspin_card is not None
    assert banner.madspin_card.startswith("set max_weight_ps_point 400")
    assert banner.madspin_card.endswith("decay w- > j j\nlaunch")
    text = BANNER.read_text().replace(
        "<MGRunCard>",
        "<MG5ProcCard>\n<![CDATA[\ngenerate p p > t t~ @0\n]]>\n</MG5ProcCard>\n"
        "<slha>\nBLOCK MASS\n    6 1.725e+02\n</slha>\n<MGRunCard>",
    )
    banner = Banner.from_text(text)
    assert banner.proc_card == "generate p p > t t~ @0"
    assert banner.param_card == "BLOCK MASS\n    6 1.725e+02"


def test_gzipped_event_file_is_read_up_to_the_first_event(tmp_path: Path) -> None:
    events = "<event>\n" + "0 0 0 0 0 0\n" * 1000 + "</event>\n"
    path = tmp_path / "unweighted_events.lhe.gz"
    with gzip.open(path, "wt") as stream:
        stream.write(BANNER.read_text() + events * 50)
    banner = Banner.read(path)
    assert banner.n_events == 10000
    assert banner.cross_section_error_pb == pytest.approx(2.398374998897e-3)


def test_text_without_a_banner_is_rejected() -> None:
    with pytest.raises(ValueError, match="MGGenerationInfo"):
        Banner.from_text("<LesHouchesEvents>\n<header>\n</header>\n")
    with pytest.raises(ValueError, match="MGVersion"):
        Banner.from_text(
            "<MGGenerationInfo>\n#  Number of Events : 1\n"
            "#  Integrated weight (pb) : 2.0\n</MGGenerationInfo>\n"
        )


def test_malformed_init_block_is_rejected() -> None:
    header = BANNER.read_text()
    header = re.sub(r"<init>.*?</init>\n", "", header, flags=re.S)
    beams = "2212 2212 6.5e3 6.5e3 0 0 247000 247000 -4 2\n"
    one_subprocess = " 1.05e+00 2.40e-03 1.05e+00 1\n"
    with pytest.raises(ValueError, match="announces 2 subprocess lines but holds 1"):
        Banner.from_text(header + "<init>\n" + beams + one_subprocess + "</init>\n")
    with pytest.raises(ValueError, match="beam line"):
        Banner.from_text(header + "<init>\n2212 2212\n</init>\n")
    with pytest.raises(ValueError, match="incomplete"):
        Banner.from_text(
            header + "<init>\n" + beams.replace(" 2\n", " 1\n") + " 1.05\n</init>\n"
        )
