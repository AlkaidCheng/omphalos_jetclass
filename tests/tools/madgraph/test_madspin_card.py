from collections.abc import Mapping

from omphjc.config_paths import config_dir
from omphjc.processes import ProcessSpec
from omphjc.tools.madgraph.cards import madspin_card_text
from omphjc.tools.madgraph.madspin_card import MadSpinCard

REFERENCES_DIR = config_dir() / "references" / "jetclass"


def test_ttbar_card_decays_both_tops_hadronically(
    specs: Mapping[str, ProcessSpec],
) -> None:
    card = MadSpinCard.from_text(madspin_card_text(specs["TTBar"]))
    assert card.options == {"max_weight_ps_point": 400}
    assert "t > w+ b, w+ > j j" in card.decays
    assert "t~ > w- b~, w- > j j" in card.decays


def test_layout_and_comments_do_not_change_the_configuration(
    specs: Mapping[str, ProcessSpec],
) -> None:
    text = madspin_card_text(specs["TTBarLep"])
    reformatted = "\n".join(
        f"{line.strip()}   # note" if line.strip().startswith("decay") else line
        for line in text.splitlines()
    ).replace("decay t > w+ b, w+ > l+ vl", "decay   t  >  w+ b,  w+ > l+  vl")
    reference = MadSpinCard.from_text(text)
    rewritten = MadSpinCard.from_text(reformatted)
    assert rewritten.differences(reference) == []
    assert rewritten.fingerprint() == reference.fingerprint()
    assert reference.fingerprint().startswith("madspin_card-v1:")


def test_the_content_record_holds_the_options_and_the_sorted_decay_chains() -> None:
    card = MadSpinCard.from_text(
        "set max_weight_ps_point 400\ndecay w+ > j j\ndecay t > w+ b, w+ > j j\n"
    )
    assert card.content_record() == {
        "options": {"max_weight_ps_point": 400},
        "decays": ["t > w+ b, w+ > j j", "w+ > j j"],
    }


def test_changed_decay_and_option_are_reported() -> None:
    reference = MadSpinCard.from_text(
        "set max_weight_ps_point 400\ndecay t > w+ b, w+ > j j\nlaunch\n"
    )
    altered = MadSpinCard.from_text(
        "set max_weight_ps_point 100\ndecay t > w+ b, w+ > l+ vl\nlaunch\n"
    )
    items = [str(d) for d in altered.differences(reference)]
    assert items == [
        "option max_weight_ps_point: expected 400, got 100",
        "missing decay: t > w+ b, w+ > j j",
        "unexpected decay: t > w+ b, w+ > l+ vl",
    ]


def test_the_card_of_a_process_is_the_card_its_entry_names(
    specs: Mapping[str, ProcessSpec],
) -> None:
    card = MadSpinCard.from_process(specs["TTBar"])
    assert card == MadSpinCard.from_text(madspin_card_text(specs["TTBar"]))


def test_a_process_without_madspin_has_no_card(
    specs: Mapping[str, ProcessSpec],
) -> None:
    assert MadSpinCard.from_process(specs["HToBB"]) is None


def test_the_official_card_is_read_from_the_reference_directory() -> None:
    card = MadSpinCard.reference(REFERENCES_DIR / "TTBar")
    assert card is not None
    assert "t > w+ b, w+ > j j" in card.decays


def test_a_reference_directory_without_a_madspin_card_has_no_card() -> None:
    assert MadSpinCard.reference(REFERENCES_DIR / "HToBB") is None
