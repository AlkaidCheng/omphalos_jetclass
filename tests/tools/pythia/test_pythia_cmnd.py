from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from omphjc.processes import ProcessSpec, get_process
from omphjc.tools.pythia.cmnd import (
    MADGRAPH_INTERFACE_PREFIXES,
    PYTHIA_SEED_LIMIT,
    PythiaCmnd,
    format_setting,
    matching_scale,
    max_matched_jets,
)

DATA = Path(__file__).parents[2] / "data" / "pythia"
LHE = Path("events.lhe")

# Settings this package writes differently from MadGraph's interface on purpose.
RUN_CONTROL = {
    "main:numberofevents",  # MadGraph's -1 (whole file); DelphesPythia8 needs a count
    "main:subrun",  # subrun bookkeeping of MadGraph's own driver
    "beams:lhef",  # the input file name
    "random:setseed",  # the seed policy is the job's
    "random:seed",
}


def madgraph_card(name: str) -> PythiaCmnd:
    return PythiaCmnd.read(DATA / f"{name}_mg311_effective.cmd")


@pytest.mark.parametrize("name", ["HToBB", "ZJetsToNuNu"])
def test_settings_equal_madgraph_effective_card(name: str) -> None:
    cmnd = PythiaCmnd.from_process(
        get_process(name), lhe_path=LHE, n_events=1000, seed=None
    )
    ignore = RUN_CONTROL | MADGRAPH_INTERFACE_PREFIXES
    assert cmnd.differences(madgraph_card(name), ignore=ignore) == []


def test_only_run_control_and_interface_keys_differ_from_madgraph() -> None:
    cmnd = PythiaCmnd.from_process(
        get_process("ZJetsToNuNu"), lhe_path=LHE, n_events=1000, seed=None
    )
    differences = cmnd.differences(madgraph_card("ZJetsToNuNu"))
    assert {difference.item.lower() for difference in differences} == RUN_CONTROL | {
        "hepmcoutput:file",
        "hepmcoutput:scaling",
        "syscalc:fullcutvariation",
        "syscalc:qweed",
        "lhefinputs:nsubruns",
    }


def test_matched_process_gets_the_mlm_block(specs: Mapping[str, ProcessSpec]) -> None:
    for spec in specs.values():
        settings = PythiaCmnd.from_process(
            spec, lhe_path=LHE, n_events=10, seed=None
        ).settings
        assert ("JetMatching:merge" in settings) == spec.matching, spec.name
        assert settings["JetMatching:setMad"] == "off"
        assert settings["Check:epTolErr"] == "0.01"


def test_matching_values_follow_madgraph_rules() -> None:
    qcd = get_process("ZJetsToNuNu")
    assert matching_scale(qcd) == pytest.approx(45.0)
    assert max_matched_jets(qcd) == 2
    settings = PythiaCmnd.from_process(
        qcd, lhe_path=LHE, n_events=10, seed=None
    ).settings
    assert settings["JetMatching:qCut"] == "45"
    assert settings["JetMatching:nJetMax"] == "2"
    assert settings["JetMatching:nQmatch"] == "5"
    assert settings["Beams:setProductionScalesFromLHEF"] == "on"


def test_matching_scale_needs_a_matched_process() -> None:
    with pytest.raises(ValueError, match="not MLM-matched"):
        matching_scale(get_process("HToBB"))
    assert max_matched_jets(get_process("HToBB")) == 0


def test_shared_settings_come_from_the_catalogue_and_overrides_win(
    specs: Mapping[str, ProcessSpec],
) -> None:
    spec = specs["HToBB"]
    assert spec.pythia == {
        "Beams:frameType": 4,
        "Check:epTolErr": 0.01,
        "JetMatching:setMad": False,
        "JetMatching:etaJetMax": 1000.0,
    }
    assert spec.pythia_matching["JetMatching:scheme"] == 1
    settings = PythiaCmnd.from_process(
        spec,
        lhe_path=LHE,
        n_events=10,
        seed=None,
        overrides={"Check:epTolErr": 0.1, "Main:timesAllowErrors": 100},
    ).settings
    assert settings["Check:epTolErr"] == "0.1"
    assert settings["Main:timesAllowErrors"] == "100"


def test_settings_are_written_as_pythia_reads_them() -> None:
    assert [format_setting(v) for v in (True, False, 4, 1000.0, 0.01, "x")] == [
        "on",
        "off",
        "4",
        "1000",
        "0.01",
        "x",
    ]


def test_seed_policy() -> None:
    spec = get_process("HToBB")
    unseeded = PythiaCmnd.from_process(
        spec, lhe_path=LHE, n_events=10, seed=None
    ).settings
    assert (unseeded["Random:setSeed"], unseeded["Random:seed"]) == ("on", "0")
    seeded = PythiaCmnd.from_process(
        spec, lhe_path=LHE, n_events=10, seed=10000007
    ).settings
    assert seeded["Random:seed"] == "10000007"
    for bad in (0, -1, PYTHIA_SEED_LIMIT + 1):
        with pytest.raises(ValueError, match="seed"):
            PythiaCmnd.from_process(spec, lhe_path=LHE, n_events=10, seed=bad)
    with pytest.raises(ValueError, match="n_events"):
        PythiaCmnd.from_process(spec, lhe_path=LHE, n_events=0, seed=None)


def test_no_setting_belongs_to_madgraph_interface(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for spec in specs.values():
        for key in PythiaCmnd.from_process(
            spec, lhe_path=LHE, n_events=10, seed=1
        ).settings:
            assert not key.lower().startswith(tuple(MADGRAPH_INTERFACE_PREFIXES)), key


def test_formatted_file_reads_back_identically(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for spec in specs.values():
        cmnd = PythiaCmnd.from_process(spec, lhe_path=LHE, n_events=500, seed=3)
        text = cmnd.to_text(title=spec.name)
        assert text.startswith("! Pythia 8 settings for DelphesPythia8")
        assert PythiaCmnd.from_text(text) == cmnd


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
    assert PythiaCmnd.from_text(text).settings == {
        "beams:frametype": "5",
        "JetMatching:qCut": "4.5000000000e+01",
    }


def test_compare_reads_values_like_pythia() -> None:
    reference = PythiaCmnd(
        {"JetMatching:merge": "on", "JetMatching:qCut": "4.5000000000e+01"}
    )
    same = PythiaCmnd({"jetmatching:MERGE": "true", "JetMatching:qCut": "45"})
    assert same.differences(reference) == []
    assert same.content_record() == reference.content_record()
    differences = PythiaCmnd({"JetMatching:merge": "off"}).differences(reference)
    assert [str(d) for d in differences] == [
        "JetMatching:merge: expected on, got off",
        "missing JetMatching:qCut: 4.5000000000e+01",
    ]
    seeded = PythiaCmnd({**reference.settings, "Random:seed": "1"})
    assert [str(d) for d in seeded.differences(reference)] == [
        "unexpected Random:seed: 1"
    ]
    assert seeded.differences(reference, ignore={"random:"}) == []


def test_the_content_record_holds_the_values_pythia_reads() -> None:
    cmnd = PythiaCmnd.from_text("JetMatching:merge = on\nJetMatching:qCut = 45\n")
    assert cmnd.content_record() == {
        "jetmatching:merge": True,
        "jetmatching:qcut": 45.0,
    }
    assert cmnd.fingerprint().startswith("pythia_cmnd-v1:")


def test_every_setting_is_known_to_pythia(specs: Mapping[str, ProcessSpec]) -> None:
    pythia8 = pytest.importorskip("pythia8")
    pythia = pythia8.Pythia("", False)
    for spec in specs.values():
        settings = PythiaCmnd.from_process(
            spec, lhe_path=LHE, n_events=10, seed=1
        ).settings
        for key, value in settings.items():
            assert pythia.readString(f"{key} = {value}"), (spec.name, key, value)


def test_catalogue_settings_override_the_derived_matching_values(
    specs: Mapping[str, ProcessSpec],
) -> None:
    spec = specs["ZJetsToNuNu"]
    tuned = replace(
        spec,
        pythia={**spec.pythia, "JetMatching:qCut": 60.0, "jetmatching:coneradius": 0.4},
    )
    settings = PythiaCmnd.from_process(
        tuned, lhe_path=LHE, n_events=10, seed=1
    ).settings
    assert settings["JetMatching:qCut"] == "60"
    assert settings["jetmatching:coneradius"] == "0.4"
    assert "JetMatching:coneRadius" not in settings
    run = PythiaCmnd.from_process(
        tuned, lhe_path=LHE, n_events=10, seed=1, overrides={"jetmatching:qcut": 70}
    ).settings
    assert run["jetmatching:qcut"] == "70"
    assert "JetMatching:qCut" not in run


def test_run_controls_override_the_catalogue(specs: Mapping[str, ProcessSpec]) -> None:
    spec = specs["HToBB"]
    tuned = replace(spec, pythia={**spec.pythia, "Main:numberOfEvents": 5})
    settings = PythiaCmnd.from_process(
        tuned, lhe_path=LHE, n_events=10, seed=None
    ).settings
    assert settings["Main:numberOfEvents"] == "10"
