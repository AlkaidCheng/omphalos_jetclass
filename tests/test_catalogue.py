from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from omphjc.config_paths import catalogue_path
from omphjc.processes import ProcessSpec, get_process, process_names, read_catalogue

JETCLASS_CLASSES = {
    "HToBB": "Hbb",
    "HToCC": "Hcc",
    "HToGG": "Hgg",
    "HToWW4Q": "H4q",
    "HToWW2Q1L": "Hqql",
    "TTBar": "Tbqq",
    "TTBarLep": "Tbl",
    "WToQQ": "Wqq",
    "ZToQQ": "Zqq",
    "ZJetsToNuNu": "QCD",
}


def test_catalogue_covers_the_ten_jetclass_classes(
    specs: Mapping[str, ProcessSpec],
) -> None:
    assert {name: spec.label for name, spec in specs.items()} == JETCLASS_CLASSES
    assert process_names() == tuple(JETCLASS_CLASSES)


def test_only_zjets_is_matched_and_only_tops_use_madspin(
    specs: Mapping[str, ProcessSpec],
) -> None:
    assert [name for name, spec in specs.items() if spec.matching] == ["ZJetsToNuNu"]
    assert [name for name, spec in specs.items() if spec.uses_madspin] == [
        "TTBar",
        "TTBarLep",
    ]


def test_seed_offsets_follow_the_official_driver(
    specs: Mapping[str, ProcessSpec],
) -> None:
    offsets = {name: spec.seed_offset for name, spec in specs.items()}
    assert offsets["HToBB"] == 10_000_000
    assert offsets["HToWW2Q1L"] == 50_000_000
    assert all(offsets[name] == 0 for name in ("TTBar", "WToQQ", "ZJetsToNuNu"))
    assert len(set(offsets.values())) == 6


def test_common_settings_are_merged_into_every_process(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for spec in specs.values():
        assert spec.definitions[:2] == ("p = p b b~", "j = j b b~")
        assert spec.run_card["ebeam1"] == 6500.0
        assert spec.run_card["pdlabel"] == "nn23lo1"
        assert spec.run_card["maxjetflavor"] == 5
        assert spec.run_card["use_syst"] is False
    assert specs["HToWW2Q1L"].definitions[2:] == ("lep = l+ l-", "nu = vl vl~")


def test_pdg_keyed_cuts_use_integer_keys(specs: Mapping[str, ProcessSpec]) -> None:
    assert specs["HToBB"].run_card["pt_min_pdg"] == {25: 450.0}
    assert specs["TTBar"].run_card["eta_max_pdg"] == {6: 2.5}


def test_model_name_splits_into_base_and_restriction(
    specs: Mapping[str, ProcessSpec],
) -> None:
    assert (specs["HToWW4Q"].model_base, specs["HToWW4Q"].model_restriction) == (
        "heft",
        "ckm",
    )
    assert specs["HToCC"].model_restriction == ""
    assert specs["ZJetsToNuNu"].model_base == "sm"


def test_vendored_models_are_resolved_and_standard_models_are_not(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for spec in specs.values():
        if spec.model_base in {"heft", "heft_c_mass_jetclass"}:
            assert spec.model_dir is not None, spec.name
            assert spec.model_dir.name == spec.model_base
            assert (spec.model_dir / "__init__.py").is_file()
            assert (spec.model_dir / "restrict_default.dat").is_file()
        else:
            assert spec.model_dir is None, spec.name
    heft = specs["HToWW4Q"].model_dir
    assert heft is not None and (heft / "restrict_ckm.dat").is_file()


def test_reference_cards_are_included_for_every_process(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for name, spec in specs.items():
        directory = spec.reference_cards
        assert directory is not None, name
        assert (directory / "run_card.dat").is_file()
        assert (directory / "proc_card_mg5.dat").is_file()
        assert (directory / f"run_{name}.mg5").is_file()
    config = catalogue_path().parent
    assert specs["TTBar"].madspin_card == config / "madspin" / "TTBar.dat"
    assert (
        specs["TTBar"].reference_cards == config / "references" / "jetclass" / "TTBar"
    )


def test_unknown_process_lists_the_known_names() -> None:
    with pytest.raises(KeyError, match="HToBB"):
        get_process("HToTauTau")


def test_load_catalogue_rejects_missing_keys(tmp_path: Path) -> None:
    broken = tmp_path / "catalogue.yaml"
    broken.write_text(
        "processes:\n  X:\n    label: X\n    model: sm\n    processes: ['p p > z']\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="lacks required keys"):
        read_catalogue(broken)


def test_load_catalogue_rejects_unknown_keys_and_missing_files(tmp_path: Path) -> None:
    entry = (
        "processes:\n  X:\n    label: X\n    description: d\n    model: sm\n"
        "    processes: ['p p > z']\n    run_card: {}\n    seed_offset: 1\n"
    )
    typo = tmp_path / "typo.yaml"
    typo.write_text(entry + "    madspin_cards: decays.dat\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown keys.*madspin_cards"):
        read_catalogue(typo)
    missing = tmp_path / "missing.yaml"
    missing.write_text(entry + "    madspin_card: decays.dat\n", encoding="utf-8")
    with pytest.raises(ValueError, match="madspin_card 'decays.dat' does not exist"):
        read_catalogue(missing)


def test_load_catalogue_rejects_duplicate_labels(tmp_path: Path) -> None:
    entry = (
        "  {name}:\n    label: Same\n    description: d\n    model: sm\n"
        "    processes: ['p p > z']\n    run_card: {{}}\n    seed_offset: 1\n"
    )
    path = tmp_path / "labels.yaml"
    path.write_text(
        "processes:\n" + entry.format(name="A") + entry.format(name="B"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"more than one process: \['Same'\]"):
        read_catalogue(path)


def test_the_delphes_card_is_named_once_for_every_process(
    specs: Mapping[str, ProcessSpec],
) -> None:
    card = catalogue_path().parent / "delphes" / "delphes_card_JetClass.tcl"
    assert {spec.delphes_card for spec in specs.values()} == {card}


def test_load_catalogue_checks_the_common_block(tmp_path: Path) -> None:
    entry = (
        "processes:\n  X:\n    label: X\n    description: d\n    model: sm\n"
        "    processes: ['p p > z']\n    run_card: {}\n"
    )
    typo = tmp_path / "typo.yaml"
    typo.write_text("common:\n  delphes_cards: d.tcl\n" + entry, encoding="utf-8")
    with pytest.raises(
        ValueError, match="common block has unknown keys.*delphes_cards"
    ):
        read_catalogue(typo)
    missing = tmp_path / "missing.yaml"
    missing.write_text("common:\n  delphes_card: d.tcl\n" + entry, encoding="utf-8")
    with pytest.raises(ValueError, match="common: delphes_card 'd.tcl' does not exist"):
        read_catalogue(missing)
    bare = tmp_path / "bare.yaml"
    bare.write_text(entry, encoding="utf-8")
    assert read_catalogue(bare)["X"].delphes_card is None


def test_an_entry_needs_only_its_physics(tmp_path: Path) -> None:
    path = tmp_path / "minimal.yaml"
    path.write_text(
        "common:\n  run_card: {ebeam1: 6800.0}\n"
        "processes:\n  Z:\n    label: Z\n    description: d\n    model: sm\n"
        "    processes: ['p p > z']\n",
        encoding="utf-8",
    )
    spec = read_catalogue(path)["Z"]
    assert spec.run_card == {"ebeam1": 6800.0}
    assert spec.definitions == ()
    assert (spec.seed_offset, spec.matching, spec.uses_madspin) == (0, False, False)


def test_paths_may_be_absolute(tmp_path: Path) -> None:
    config = catalogue_path().parent
    path = tmp_path / "elsewhere" / "absolute.yaml"
    path.parent.mkdir()
    path.write_text(
        f"common:\n  models_dir: {config / 'models'}\n"
        f"  delphes_card: {config / 'delphes' / 'delphes_card_JetClass.tcl'}\n"
        "processes:\n  T:\n    label: T\n    description: d\n    model: heft\n"
        "    processes: ['p p > t t~']\n"
        f"    madspin_card: {config / 'madspin' / 'TTBar.dat'}\n"
        f"    reference_cards: {config / 'references' / 'jetclass' / 'TTBar'}\n",
        encoding="utf-8",
    )
    spec = read_catalogue(path)["T"]
    assert spec.model_dir == config / "models" / "heft"
    assert spec.delphes_card == config / "delphes" / "delphes_card_JetClass.tcl"
    assert spec.madspin_card == config / "madspin" / "TTBar.dat"
    assert spec.reference_cards == config / "references" / "jetclass" / "TTBar"


@pytest.mark.parametrize("name", ["", ".", "..", "../x", "/etc", "a/b", "my run", "-x"])
def test_a_process_name_that_is_not_plain_is_rejected(
    specs: Mapping[str, ProcessSpec], name: str
) -> None:
    with pytest.raises(ValueError, match="Process name"):
        replace(specs["HToBB"], name=name)


@pytest.mark.parametrize("model", ["", "..", "../heft", "/abs/heft", "a/b", "a-b-c"])
def test_a_model_name_that_is_not_plain_is_rejected(
    specs: Mapping[str, ProcessSpec], model: str
) -> None:
    with pytest.raises(ValueError, match="model"):
        replace(specs["HToBB"], model=model)
