from collections.abc import Mapping

from omphjc.processes import ProcessSpec
from omphjc.tools.madgraph.cards import madspin_card_text
from omphjc.tools.madgraph.madspin_card import MadSpinCard


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
    assert reference.fingerprint().startswith("madspin-card-v1:")


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
