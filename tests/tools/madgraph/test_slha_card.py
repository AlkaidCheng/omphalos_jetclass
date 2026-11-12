from omphjc.tools.madgraph.slha_card import SLHACard

CARD = """\
# written by MadGraph
Block MASS  # pole masses
    6 1.725000e+02 # MT
   25 1.250000e+02 # MH
Block YUKAWA
    6 1.725000e+02 # ymt
DECAY   6 1.491500e+00 # WT
   1.000000e+00   2    5   24 # t > b w+
"""


def test_an_slha_card_holds_one_entry_for_each_line_under_its_block_or_decay() -> None:
    assert SLHACard.from_text(CARD).entries == (
        ("block", "mass"),
        ("block", "mass", 6, 172.5),
        ("block", "mass", 25, 125.0),
        ("block", "yukawa"),
        ("block", "yukawa", 6, 172.5),
        ("decay", 6, 1.4915),
        ("decay", 6, 1.4915, 1.0, 2, 5, 24),
    )


def test_the_content_record_is_the_entries_in_sorted_order() -> None:
    assert SLHACard.from_text(CARD).content_record() == [
        ["block", "mass", 25, 125.0],
        ["block", "mass", 6, 172.5],
        ["block", "mass"],
        ["block", "yukawa", 6, 172.5],
        ["block", "yukawa"],
        ["decay", 6, 1.4915, 1.0, 2, 5, 24],
        ["decay", 6, 1.4915],
    ]


def test_layout_case_and_the_order_of_blocks_do_not_change_the_fingerprint() -> None:
    card = SLHACard.from_text(CARD)
    rewritten = SLHACard.from_text(
        "decay 6 1.4915\n 1.0 2 5 24\n"
        "BLOCK yukawa\n 6 172.5\n"
        "BLOCK mass\n 25 125.0\n 6 172.5\n"
    )
    assert rewritten.entries != card.entries
    assert rewritten.fingerprint() == card.fingerprint()
    assert card.fingerprint().startswith("slha-v1:")


def test_a_parameter_moved_to_another_block_changes_the_fingerprint() -> None:
    card = SLHACard.from_text("Block MASS\n 6 172.5\nBlock YUKAWA\n")
    moved = SLHACard.from_text("Block MASS\nBlock YUKAWA\n 6 172.5\n")
    assert moved.fingerprint() != card.fingerprint()


def test_a_changed_value_changes_the_fingerprint() -> None:
    card = SLHACard.from_text(CARD)
    other = SLHACard.from_text(CARD.replace("1.725000e+02 # MT", "1.730000e+02 # MT"))
    assert other.fingerprint() != card.fingerprint()


def test_cards_that_differ_only_in_layout_have_no_differences() -> None:
    card = SLHACard.from_text(CARD)
    rewritten = SLHACard.from_text(
        "decay 6 1.4915\n 1.0 2 5 24\n"
        "BLOCK yukawa\n 6 172.5\n"
        "BLOCK mass\n 25 125.0\n 6 172.5\n"
    )
    assert rewritten.differences(card) == []


def test_a_changed_value_is_reported_as_one_entry_of_each_card() -> None:
    reference = SLHACard.from_text(CARD)
    card = SLHACard.from_text(CARD.replace("1.725000e+02 # MT", "1.730000e+02 # MT"))
    assert [str(difference) for difference in card.differences(reference)] == [
        "block mass 6 172.5: expected present, got absent",
        "block mass 6 173.0: expected absent, got present",
    ]
