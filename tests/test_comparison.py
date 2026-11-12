from omphjc.comparison import Difference


def test_mappings_differ_in_each_key_with_two_values() -> None:
    differences = Difference.between_mappings(
        {"ptj": 20, "etaj": 5, "iseed": 42}, {"ptj": 10, "etaj": 5, "nevents": 100}
    )
    assert [str(difference) for difference in differences] == [
        "unexpected iseed: 42",
        "missing nevents: 100",
        "ptj: expected 10, got 20",
    ]


def test_values_are_compared_and_written_by_the_given_functions() -> None:
    differences = Difference.between_mappings(
        {"mode": "ON", "cut": 2.5},
        {"mode": "on", "cut": 3.0},
        equal=lambda left, right: str(left).lower() == str(right).lower(),
        text=repr,
        name="option {}".format,
    )
    assert differences == [Difference("option cut", "3.0", "2.5")]


def test_collections_differ_in_each_member_that_one_alone_holds() -> None:
    differences = Difference.between_collections(
        ["b", "c", "d"], ["a", "b", "e"], item="letter"
    )
    assert [str(difference) for difference in differences] == [
        "missing letter: a",
        "missing letter: e",
        "unexpected letter: c",
        "unexpected letter: d",
    ]


def test_a_member_is_written_by_the_given_function() -> None:
    differences = Difference.between_collections(
        [("mass", 6, 173.0)],
        [("mass", 6, 172.5)],
        item="entry",
        text=lambda entry: " ".join(str(word) for word in entry),
    )
    assert differences == [
        Difference("entry", "mass 6 172.5", None),
        Difference("entry", None, "mass 6 173.0"),
    ]


def test_equal_mappings_and_equal_collections_have_no_differences() -> None:
    assert Difference.between_mappings({"ptj": 20}, {"ptj": 20}) == []
    assert Difference.between_collections(["a", "b"], ["b", "a"], item="letter") == []
