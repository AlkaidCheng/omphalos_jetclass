from collections.abc import Mapping

from omphjc.madgraph import (
    compare_madspin_cards,
    madspin_card_text,
    parse_madspin_card,
)
from omphjc.processes import ProcessSpec


def test_official_top_card_decays_both_tops_hadronically(
    specs: Mapping[str, ProcessSpec],
) -> None:
    card = parse_madspin_card(madspin_card_text(specs["TTBar"]))
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
    reference = parse_madspin_card(text)
    assert compare_madspin_cards(parse_madspin_card(reformatted), reference) == []


def test_changed_decay_and_option_are_reported() -> None:
    reference = parse_madspin_card(
        "set max_weight_ps_point 400\ndecay t > w+ b, w+ > j j\nlaunch\n"
    )
    altered = parse_madspin_card(
        "set max_weight_ps_point 100\ndecay t > w+ b, w+ > l+ vl\nlaunch\n"
    )
    items = [str(d) for d in compare_madspin_cards(altered, reference)]
    assert items == [
        "option max_weight_ps_point: expected 400, got 100",
        "decay t > w+ b, w+ > j j: expected present, got absent",
        "decay t > w+ b, w+ > l+ vl: expected absent, got present",
    ]
