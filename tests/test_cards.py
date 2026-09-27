from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.config_paths import models_dir, reference_dir
from omphjc.madgraph import (
    DISABLED_DEFAULTS,
    TRACKED_PARAMETERS,
    compare_all,
    compare_process,
    launch_commands,
    madspin_card_text,
    model_import_target,
    proc_card_commands,
    reference_proc_lines,
    reference_run_settings,
)
from omphjc.processes import ProcessSpec


def test_catalogue_matches_the_official_gridpack_cards() -> None:
    assert compare_all() == []


def test_every_tracked_official_setting_is_pinned(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for name, spec in specs.items():
        reference = reference_run_settings(name)
        expected = {
            key
            for key in TRACKED_PARAMETERS & reference.keys()
            if reference[key] != DISABLED_DEFAULTS.get(key)
        }
        assert expected <= spec.run_card.keys(), name


def test_a_changed_cut_is_reported(specs: Mapping[str, ProcessSpec]) -> None:
    original = specs["HToBB"]
    altered = ProcessSpec(
        **{**original.__dict__, "run_card": {**original.run_card, "misset": 400.0}}
    )
    mismatches = compare_process(altered)
    assert [m.item for m in mismatches] == ["run_card.misset"]
    assert mismatches[0].expected == "450.0"
    assert mismatches[0].actual == "400.0"


def test_a_missing_tracked_setting_is_reported(
    specs: Mapping[str, ProcessSpec],
) -> None:
    original = specs["HToWW2Q1L"]
    run_card = {key: value for key, value in original.run_card.items() if key != "ptl"}
    altered = ProcessSpec(**{**original.__dict__, "run_card": run_card})
    mismatches = compare_process(altered)
    assert [m.item for m in mismatches] == ["run_card.ptl"]
    assert mismatches[0].actual == "absent"


def test_proc_card_commands_for_a_matched_process(
    specs: Mapping[str, ProcessSpec],
) -> None:
    commands = proc_card_commands(
        specs["ZJetsToNuNu"], output_dir=Path("out"), models_dir=Path("models")
    )
    assert commands == [
        "import model sm",
        "define p = p b b~",
        "define j = j b b~",
        "generate p p > ve ve~ j @0",
        "add process p p > ve ve~ j j @1",
        "output out",
    ]


def test_vendored_models_are_imported_by_path(
    specs: Mapping[str, ProcessSpec],
) -> None:
    directory = models_dir()
    assert (
        model_import_target(specs["HToWW4Q"], models_dir=directory)
        == str(directory / "heft") + "-ckm"
    )
    assert model_import_target(specs["HToCC"], models_dir=directory) == str(
        directory / "heft_c_mass_jetclass"
    )
    assert model_import_target(specs["TTBar"], models_dir=directory) == "sm-ckm"


def test_reference_proc_lines_drop_the_madgraph_preamble() -> None:
    assert reference_proc_lines("HToBB") == [
        "import model heft",
        "define p = p b b~",
        "define j = j b b~",
        "generate p p > ve ve~ h, h > b b~",
    ]
    assert reference_proc_lines("ZJetsToNuNu")[0] == "import model sm"
    assert reference_proc_lines("HToCC")[0] == "import model heft_c_mass_jetclass"


def test_launch_commands_switch_shower_and_detector_off(
    specs: Mapping[str, ProcessSpec],
) -> None:
    commands = launch_commands(
        specs["TTBar"], process_dir=Path("TTBar"), n_events=1000, seed=7
    )
    assert commands[:5] == [
        "launch TTBar",
        "shower=OFF",
        "detector=OFF",
        "madspin=ON",
        "done",
    ]
    assert "set nevents 1000" in commands
    assert "set iseed 7" in commands
    assert "set pt_min_pdg {6: 450.0}" in commands
    assert "set use_syst False" in commands
    assert commands[-1] == "done"


def test_launch_commands_without_a_seed_let_madgraph_choose(
    specs: Mapping[str, ProcessSpec],
) -> None:
    commands = launch_commands(
        specs["HToBB"], process_dir=Path("HToBB"), n_events=10, seed=None
    )
    assert "set iseed 0" in commands
    assert "madspin=OFF" in commands


def test_launch_commands_reject_a_non_positive_event_count(
    specs: Mapping[str, ProcessSpec],
) -> None:
    with pytest.raises(ValueError, match="positive"):
        launch_commands(specs["HToBB"], process_dir=Path("x"), n_events=0, seed=1)


def test_madspin_card_is_the_official_one(specs: Mapping[str, ProcessSpec]) -> None:
    text = madspin_card_text(specs["TTBarLep"])
    assert text == (reference_dir("TTBarLep") / "madspin_card.dat").read_text("utf-8")
    assert "decay t > w+ b, w+ > l+ vl" in text
    with pytest.raises(ValueError, match="does not use MadSpin"):
        madspin_card_text(specs["HToBB"])


def test_a_tracked_cut_at_its_disabled_default_needs_no_entry(
    specs: Mapping[str, ProcessSpec],
) -> None:
    reference = reference_run_settings("WToQQ")
    assert reference["pt_min_pdg"] == {}
    assert "pt_min_pdg" not in specs["WToQQ"].run_card
    assert compare_process(specs["WToQQ"]) == []
