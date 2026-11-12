import re
import sys

import pytest

from omphjc.config_paths import config_dir
from omphjc.processes import get_process
from omphjc.tools.delphes.card import (
    DelphesCard,
    reference_card,
    reference_card_text,
    with_random_seed,
)


def test_reference_card_evaluates_to_the_jetclass_configuration() -> None:
    card = reference_card()
    assert card.execution_path[:2] == (
        "ParticlePropagator",
        "ChargedHadronTrackingEfficiency",
    )
    assert "TrackSmearing" in card.execution_path
    assert card.execution_path[-1] == "TreeWriter"
    assert card.settings == {}

    fat_jets = card.modules["FatJetFinder"]
    assert fat_jets.type == "FastJetFinder"
    assert fat_jets.parameters["ParameterR"] == ("0.8",)
    assert fat_jets.parameters["JetPTMin"] == ("500.0",)
    assert fat_jets.parameters["ComputeSoftDrop"] == ("1",)
    assert fat_jets.parameters["InputArray"] == ("EFlowMerger/eflow",)

    branches = card.modules["TreeWriter"].parameters["Branch"]
    assert branches[:3] == ("Delphes/allParticles", "Particle", "GenParticle")
    assert len(branches) == 12


def test_calorimeter_binning_loops_are_evaluated() -> None:
    ecal = reference_card().modules["ECal"].parameters
    assert ecal["EnergyMin"] == ("0.5",)
    phi_bins = ecal["PhiBins"]
    assert len(phi_bins) == 37  # the last loop in the block: 10-degree bins
    assert float(phi_bins[0]) == pytest.approx(-3.141592653589793)
    assert len(ecal["EtaPhiBins"]) > 100


def test_layout_changes_do_not_change_the_configuration() -> None:
    text = reference_card_text()
    reformatted = "# A comment at the top\n" + re.sub(r"^ {2}", "\t", text, flags=re.M)
    reformatted = reformatted.replace(
        "set ParameterR 0.8", "set   ParameterR   0.8 ;# jet radius"
    )
    assert DelphesCard.from_text(reformatted).differences(reference_card()) == []


def test_module_definition_order_does_not_matter() -> None:
    text = reference_card_text()
    start = text.index("module FastJetFinder GenJetFinder")
    middle = text.index("module FastJetFinder FatJetFinder")
    end = text.index("module TreeWriter")
    reordered = text[:start] + text[middle:end] + text[start:middle] + text[end:]
    card = DelphesCard.from_text(reordered)
    assert card.differences(reference_card()) == []
    assert card.fingerprint() == reference_card().fingerprint()


def test_the_content_record_holds_the_evaluated_configuration() -> None:
    card = DelphesCard.from_text(
        "set ExecutionPath {Jets}\n"
        "set RandomSeed 7\n"
        "module FastJetFinder Jets {\n"
        "  set ParameterR 0.8\n"
        "  add Branch a b\n"
        "}\n"
    )
    assert card.content_record() == {
        "execution_path": ["Jets"],
        "settings": {"RandomSeed": ["7"]},
        "modules": {
            "Jets": {
                "type": "FastJetFinder",
                "parameters": {"Branch": ["a", "b"], "ParameterR": ["0.8"]},
            }
        },
    }
    assert card.fingerprint().startswith("delphes_card-v1:")


def test_changed_values_are_reported_by_module_and_parameter() -> None:
    text = reference_card_text().replace(
        "set ParameterR 0.8\n\n  set ComputeNsubjettiness",
        "set ParameterR 0.5\n\n  set ComputeNsubjettiness",
        1,
    )
    text = text.replace("  TrackSmearing\n", "", 1)
    differences = DelphesCard.from_text(text).differences(reference_card())
    items = {difference.item: difference for difference in differences}
    assert set(items) == {"ExecutionPath", "GenJetFinder.ParameterR"}
    assert items["GenJetFinder.ParameterR"].expected == "0.8"
    assert items["GenJetFinder.ParameterR"].actual == "0.5"
    assert "TrackSmearing" not in items["ExecutionPath"].actual


def test_missing_and_extra_modules_are_reported() -> None:
    text = reference_card_text().replace(
        "module TrackSmearing TrackSmearing", "module TrackSmearing TrackSmearingAlt", 1
    )
    differences = DelphesCard.from_text(text).differences(reference_card())
    assert [str(difference) for difference in differences] == [
        "missing module: TrackSmearing",
        "unexpected module: TrackSmearingAlt",
    ]


def test_random_seed_becomes_a_top_level_setting() -> None:
    seeded = DelphesCard.from_text(with_random_seed(reference_card_text(), 12345))
    assert seeded.settings == {"RandomSeed": ("12345",)}
    differences = seeded.differences(reference_card())
    assert [difference.item for difference in differences] == ["settings.RandomSeed"]
    assert differences[0].actual == "12345"


@pytest.mark.parametrize("ending", ["\n", ""])
def test_the_seed_replaces_one_the_card_sets(ending: str) -> None:
    seeded = with_random_seed(f"set RandomSeed 5{ending}", 12345)
    assert DelphesCard.from_text(seeded).settings == {"RandomSeed": ("12345",)}


def test_invalid_tcl_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not evaluate"):
        DelphesCard.from_text("module FastJetFinder Broken {\n  set ParameterR\n")


def test_a_python_without_tkinter_is_pointed_to_the_readme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "tkinter", None)
    with pytest.raises(ModuleNotFoundError, match="tkinter.*Installation") as error:
        DelphesCard.from_text("set RandomSeed 1\n")
    assert error.value.name == "tkinter"


def test_the_card_a_run_reads_starts_as_the_official_one() -> None:
    card = get_process("HToBB").delphes_card
    assert card is not None
    assert DelphesCard.read(card).differences(reference_card()) == []


def test_the_jetclass_card_adapts_the_delphes_cms_card() -> None:
    cms = DelphesCard.read(
        config_dir() / "references" / "delphes" / "delphes_card_CMS.tcl"
    )
    differences = reference_card().differences(cms)
    modules = [d for d in differences if d.item == "module"]
    removed = {d.expected for d in modules if d.actual is None}
    added = {d.actual for d in modules if d.expected is None}
    assert added == {"TrackSmearing"}
    assert removed == {
        "BTagging",
        "ChargedHadronFilter",
        "EFlowFilter",
        "ElectronEfficiency",
        "ElectronFilter",
        "ElectronIsolation",
        "FastJetFinder",
        "GenMissingET",
        "JetEnergyScale",
        "JetFlavorAssociation",
        "MissingET",
        "MuonEfficiency",
        "MuonIsolation",
        "PhotonEfficiency",
        "PhotonIsolation",
        "ScalarHT",
        "TauTagging",
        "UniqueObjectFinder",
    }
    adapted = {"ExecutionPath", "FatJetFinder", "GenJetFinder", "TreeWriter"}
    changed_cms_parameters = {
        d.item
        for d in differences
        if d not in modules and d.item.partition(".")[0] not in adapted
    }
    assert changed_cms_parameters == {"ECal.TrackInputArray"}
