"""A catalogue with a process of its own, beyond the ten JetClass classes."""

from collections.abc import Mapping
from pathlib import Path

import pytest
from click.testing import CliRunner

from omphjc.cli import cli
from omphjc.config_paths import config_root
from omphjc.jobs import derive_seeds
from omphjc.madgraph import (
    compare_all,
    launch_commands,
    madspin_card_text,
    model_import_target,
    proc_card_commands,
    reference_run_settings,
)
from omphjc.processes import ProcessSpec, load_catalogue
from omphjc.pythia import shower_settings

CATALOGUE = """\
common:
  run_card:
    lpp1: 1
    lpp2: 1
    ebeam1: 6500.0
    ebeam2: 6500.0
    pdlabel: nn23lo1
    lhaid: 230000
    fixed_ren_scale: false
    fixed_fac_scale: false
    dynamical_scale_choice: -1
    scalefact: 1.0
    bwcutoff: 15.0
    maxjetflavor: 5
    use_syst: false
  pythia:
    Beams:frameType: 4
    Check:epTolErr: 0.01
    JetMatching:setMad: off
    JetMatching:etaJetMax: 1000.0
  pythia_matching:
    Beams:setProductionScalesFromLHEF: on
    JetMatching:merge: on
    JetMatching:scheme: 1
    JetMatching:coneRadius: 1.0
    JetMatching:doShowerKt: off

processes:
  ZPrimeToTT:
    label: Zptt
    description: "Z' → tt̄ with up to one extra jet"
    model: zprime-restricted
    definitions:
      - "tops = t t~"
    processes:
      - "p p > zp > tops tops @0"
      - "p p > zp > tops tops j @1"
    run_card:
      ickkw: 1
      xqcut: 40.0
      pt_min_pdg: {{6: 450.0}}
    madspin_card: decays/zprime_madspin.dat
    matching: true
    pythia:
      Main:timesAllowErrors: 50
    seed_offset: 60000000

  HToBBStudy:
    label: HbbStudy
    description: "HToBB with a lower recoil cut"
    model: heft
    processes:
      - "p p > ve ve~ h, h > b b~"
    run_card:
      cut_decays: false
      ptj: 0.1
      etaj: 5.0
      drjj: 0.01
      misset: 400.0
      pt_min_pdg: {{25: 450.0}}
      eta_max_pdg: {{25: 2.5}}
    reference_cards: {shipped}/cards/jetclass/HToBB
    seed_offset: 70000000
"""


@pytest.fixture
def study(tmp_path: Path) -> Path:
    (tmp_path / "models" / "zprime").mkdir(parents=True)
    (tmp_path / "models" / "zprime" / "__init__.py").write_text("")
    (tmp_path / "decays").mkdir()
    (tmp_path / "decays" / "zprime_madspin.dat").write_text(
        "set spinmode none\ndecay t > w+ b, w+ > j j\ndecay t~ > w- b~, w- > j j\n"
    )
    path = tmp_path / "study.yaml"
    path.write_text(CATALOGUE.format(shipped=config_root()), encoding="utf-8")
    return path


@pytest.fixture
def specs(study: Path) -> Mapping[str, ProcessSpec]:
    return load_catalogue(study)


def test_new_process_needs_only_a_catalogue_entry(
    specs: Mapping[str, ProcessSpec], study: Path
) -> None:
    spec = specs["ZPrimeToTT"]
    assert spec.model_path == study.parent / "models" / "zprime"
    assert (
        model_import_target(spec) == f"{study.parent / 'models' / 'zprime'}-restricted"
    )
    assert spec.madspin and spec.reference_cards is None
    assert proc_card_commands(spec, output_dir=Path("out"))[1:5] == [
        "define p = p b b~",
        "define j = j b b~",
        "define tops = t t~",
        "generate p p > zp > tops tops @0",
    ]
    assert "madspin=ON" in launch_commands(
        spec, process_dir=Path("x"), n_events=10, seed=None
    )
    assert "decay t > w+ b, w+ > j j" in madspin_card_text(spec)
    settings = shower_settings(spec, lhe_path=Path("e.lhe"), n_events=10, seed=None)
    assert settings["JetMatching:qCut"] == "60"
    assert settings["JetMatching:nJetMax"] == "1"
    assert settings["JetMatching:scheme"] == "1"
    assert settings["Main:timesAllowErrors"] == "50"
    assert derive_seeds(spec, 1).madgraph == 60000001


def test_matched_process_needs_the_matching_block(tmp_path: Path) -> None:
    path = tmp_path / "unmatched.yaml"
    path.write_text(
        "processes:\n  X:\n    label: X\n    description: d\n    model: sm\n"
        "    processes: ['p p > z j']\n    run_card: {ickkw: 1, xqcut: 30.0}\n"
        "    matching: true\n    seed_offset: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="JetMatching:merge"):
        load_catalogue(path)


def test_processes_without_reference_cards_are_not_checked(
    specs: Mapping[str, ProcessSpec],
) -> None:
    with pytest.raises(ValueError, match="no reference cards"):
        reference_run_settings(specs["ZPrimeToTT"])
    mismatches = compare_all(specs.values())
    assert [(m.process, m.item) for m in mismatches] == [
        ("HToBBStudy", "run_card.misset")
    ]


def test_cli_runs_on_the_study_catalogue(study: Path) -> None:
    listing = CliRunner().invoke(cli, ["--catalogue", str(study), "processes"])
    assert listing.exit_code == 0, listing.output
    assert "ZPrimeToTT   Zptt   zprime-restricted      yes      yes" in listing.output

    shown = CliRunner().invoke(
        cli, ["--catalogue", str(study), "processes", "show", "ZPrimeToTT"]
    )
    assert shown.exit_code == 0, shown.output
    assert "import model " + str(study.parent / "models" / "zprime") in shown.output

    check = CliRunner().invoke(cli, ["--catalogue", str(study), "check-cards"])
    assert check.exit_code == 1
    assert "Without reference cards, not checked: ZPrimeToTT" in check.output
    assert "HToBBStudy: run_card.misset: expected 450.0, got 400.0" in check.output
