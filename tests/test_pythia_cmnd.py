from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.processes import ProcessSpec, get_process
from omphjc.pythia import (
    MADGRAPH_INTERFACE_PREFIXES,
    PYTHIA_SEED_LIMIT,
    compare_settings,
    matching_scale,
    max_matched_jets,
    parse_cmnd,
    render_cmnd,
    shower_settings,
)

DATA = Path(__file__).parent / "data" / "pythia"
LHE = Path("events.lhe")

# Settings this package writes differently from MadGraph's interface on purpose.
RUN_CONTROL = {
    "main:numberofevents",  # MadGraph's -1 (whole file); DelphesPythia8 needs a count
    "main:subrun",  # subrun bookkeeping of MadGraph's own driver
    "beams:lhef",  # the input file name
    "random:setseed",  # the seed policy is the job's
    "random:seed",
}


def madgraph_card(name: str) -> dict[str, str]:
    return parse_cmnd((DATA / f"{name}_mg311_effective.cmd").read_text())


@pytest.mark.parametrize("name", ["HToBB", "ZJetsToNuNu"])
def test_settings_equal_madgraph_effective_card(name: str) -> None:
    settings = shower_settings(
        get_process(name), lhe_path=LHE, n_events=1000, seed=None
    )
    ignore = RUN_CONTROL | MADGRAPH_INTERFACE_PREFIXES
    assert compare_settings(settings, madgraph_card(name), ignore=ignore) == []


def test_only_run_control_and_interface_keys_differ_from_madgraph() -> None:
    settings = shower_settings(
        get_process("ZJetsToNuNu"), lhe_path=LHE, n_events=1000, seed=None
    )
    differences = compare_settings(settings, madgraph_card("ZJetsToNuNu"))
    assert {difference.item.lower() for difference in differences} == RUN_CONTROL | {
        "hepmcoutput:file",
        "hepmcoutput:scaling",
        "syscalc:fullcutvariation",
        "syscalc:qweed",
        "lhefinputs:nsubruns",
    }


def test_matched_process_gets_the_mlm_block(specs: Mapping[str, ProcessSpec]) -> None:
    for spec in specs.values():
        settings = shower_settings(spec, lhe_path=LHE, n_events=10, seed=None)
        assert ("JetMatching:merge" in settings) == spec.matching, spec.name
        assert settings["JetMatching:setMad"] == "off"
        assert settings["Check:epTolErr"] == "0.01"


def test_matching_values_follow_madgraph_rules() -> None:
    qcd = get_process("ZJetsToNuNu")
    assert matching_scale(qcd) == pytest.approx(45.0)
    assert max_matched_jets(qcd) == 2
    settings = shower_settings(qcd, lhe_path=LHE, n_events=10, seed=None)
    assert settings["JetMatching:qCut"] == "45"
    assert settings["JetMatching:nJetMax"] == "2"
    assert settings["JetMatching:nQmatch"] == "5"
    assert settings["Beams:setProductionScalesFromLHEF"] == "on"


def test_matching_scale_needs_a_matched_process() -> None:
    with pytest.raises(ValueError, match="not MLM-matched"):
        matching_scale(get_process("HToBB"))
    assert max_matched_jets(get_process("HToBB")) == 0


def test_seed_policy() -> None:
    spec = get_process("HToBB")
    unseeded = shower_settings(spec, lhe_path=LHE, n_events=10, seed=None)
    assert (unseeded["Random:setSeed"], unseeded["Random:seed"]) == ("on", "0")
    seeded = shower_settings(spec, lhe_path=LHE, n_events=10, seed=10000007)
    assert seeded["Random:seed"] == "10000007"
    for bad in (0, -1, PYTHIA_SEED_LIMIT + 1):
        with pytest.raises(ValueError, match="seed"):
            shower_settings(spec, lhe_path=LHE, n_events=10, seed=bad)
    with pytest.raises(ValueError, match="n_events"):
        shower_settings(spec, lhe_path=LHE, n_events=0, seed=None)


def test_no_setting_belongs_to_madgraph_interface(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for spec in specs.values():
        for key in shower_settings(spec, lhe_path=LHE, n_events=10, seed=1):
            assert not key.lower().startswith(tuple(MADGRAPH_INTERFACE_PREFIXES)), key


def test_rendered_file_reads_back_identically(specs: Mapping[str, ProcessSpec]) -> None:
    for spec in specs.values():
        settings = shower_settings(spec, lhe_path=LHE, n_events=500, seed=3)
        text = render_cmnd(settings, title=spec.name)
        assert text.startswith("! Pythia 8 settings for DelphesPythia8")
        assert parse_cmnd(text) == settings


def test_parse_follows_pythia_reading_rules() -> None:
    text = (
        "! comment\n"
        "  # another comment\n"
        "Beams:frameType = 4\n"
        "beams:frametype = 5  ! last occurrence wins, case-insensitively\n"
        "JetMatching:qCut=4.5000000000e+01\n"
        "Merging:TMS\n"
        "\n"
    )
    assert parse_cmnd(text) == {
        "beams:frametype": "5",
        "JetMatching:qCut": "4.5000000000e+01",
    }


def test_compare_reads_values_like_pythia() -> None:
    reference = {"JetMatching:merge": "on", "JetMatching:qCut": "4.5000000000e+01"}
    assert (
        compare_settings(
            {"jetmatching:MERGE": "true", "JetMatching:qCut": "45"}, reference
        )
        == []
    )
    differences = compare_settings({"JetMatching:merge": "off"}, reference)
    assert [str(d) for d in differences] == [
        "JetMatching:merge: expected on, got off",
        "JetMatching:qCut: expected 4.5000000000e+01, got absent",
    ]
    extra = compare_settings({**reference, "Random:seed": "1"}, reference)
    assert [str(d) for d in extra] == ["Random:seed: expected absent, got 1"]
    assert (
        compare_settings(
            {**reference, "Random:seed": "1"}, reference, ignore={"random:"}
        )
        == []
    )


def test_every_setting_is_known_to_pythia(specs: Mapping[str, ProcessSpec]) -> None:
    pythia8 = pytest.importorskip("pythia8")
    pythia = pythia8.Pythia("", False)
    for spec in specs.values():
        settings = shower_settings(spec, lhe_path=LHE, n_events=10, seed=1)
        for key, value in settings.items():
            assert pythia.readString(f"{key} = {value}"), (spec.name, key, value)
