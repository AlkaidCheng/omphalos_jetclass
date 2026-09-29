from collections.abc import Mapping
from pathlib import Path

import pytest

from omphjc.processes import ProcessSpec, get_process, load_catalogue, process_names

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
    assert [name for name, spec in specs.items() if spec.madspin] == [
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
        assert spec.run_card["ebeam1"] == 6500.0
        assert spec.run_card["pdlabel"] == "nn23lo1"
        assert spec.run_card["maxjetflavor"] == 5
        assert spec.run_card["use_syst"] is False


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


def test_shipped_models_are_resolved_and_standard_models_are_not(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for spec in specs.values():
        if spec.model_base in {"heft", "heft_c_mass_jetclass"}:
            assert spec.model_path is not None, spec.name
            assert spec.model_path.name == spec.model_base
            assert (spec.model_path / "__init__.py").is_file()
            assert (spec.model_path / "restrict_default.dat").is_file()
        else:
            assert spec.model_path is None, spec.name
    heft = specs["HToWW4Q"].model_path
    assert heft is not None and (heft / "restrict_ckm.dat").is_file()


def test_reference_cards_are_shipped_for_every_process(
    specs: Mapping[str, ProcessSpec],
) -> None:
    for name, spec in specs.items():
        directory = spec.reference_cards
        assert directory is not None, name
        assert (directory / "run_card.dat").is_file()
        assert (directory / "proc_card_mg5.dat").is_file()
        assert (directory / f"run_{name}.mg5").is_file()
    assert (
        specs["TTBar"].madspin_card
        == specs["TTBar"].reference_cards / "madspin_card.dat"
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
        load_catalogue(broken)


def test_load_catalogue_rejects_unknown_keys_and_missing_files(tmp_path: Path) -> None:
    entry = (
        "processes:\n  X:\n    label: X\n    description: d\n    model: sm\n"
        "    processes: ['p p > z']\n    run_card: {}\n    seed_offset: 1\n"
    )
    typo = tmp_path / "typo.yaml"
    typo.write_text(entry + "    madspin_cards: decays.dat\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown keys.*madspin_cards"):
        load_catalogue(typo)
    missing = tmp_path / "missing.yaml"
    missing.write_text(entry + "    madspin_card: decays.dat\n", encoding="utf-8")
    with pytest.raises(ValueError, match="madspin_card 'decays.dat' does not exist"):
        load_catalogue(missing)


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
        load_catalogue(path)
