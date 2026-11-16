import doctest

import pytest

from omphjc.tools.madgraph import multiparticles
from omphjc.tools.madgraph.multiparticles import Multiparticles


def final_definitions(*definitions: str) -> list[str]:
    return Multiparticles.from_definitions(definitions).definitions()


@pytest.mark.parametrize(
    ("definitions", "final"),
    [
        (["p = g u d"], ["p = g u d"]),
        (["p g u d"], ["p = g u d"]),
        (["p=g u d"], ["p = g u d"]),
        (["q = 21 2 -2"], ["q = 21 2 -2"]),
        (["p = g u d", "p = p b b~"], ["p = g u d b b~"]),
        (["p = g u d", "j = p"], ["p = g u d", "j = g u d"]),
        (["p = g u d", "q = p u b u"], ["p = g u d", "q = g u d b"]),
        (["p = g", "j = g", "p = u"], ["p = u", "j = g"]),
        (["p = g u", "j = p", "p = p b"], ["p = g u b", "j = g u"]),
        (["lep = l+ l-", "l+ = e+ mu+"], ["lep = l+ l-", "l+ = e+ mu+"]),
    ],
)
def test_a_label_has_the_members_of_its_last_definition(
    definitions: list[str], final: list[str]
) -> None:
    assert final_definitions(*definitions) == final


@pytest.mark.parametrize(
    ("definition", "final"),
    [
        ("q = p b / g d", "q = u b"),
        ("q = p/g", "q = u d"),
        ("q = p / ud", "q = g"),
        ("q = p / b", "q = g u d"),
        ("q = p / p", "q ="),
        ("q = p / g | u", "q = g u d"),
    ],
)
def test_the_particles_after_a_slash_are_taken_out(definition: str, final: str) -> None:
    assert final_definitions("p = g u d", "ud = u d", definition)[-1] == final


@pytest.mark.parametrize(
    ("definition", "final"),
    [
        ("q = w+ | w-", "q = w+ | w-"),
        ("q=w+|w-", "q = w+ | w-"),
        ("q = | w+", "q = w+"),
        ("q = w+ |", "q = w+ |"),
        ("q = p u | u p", "q = g u d | u g d"),
        ("q = v h", "q = z h | a h"),
        ("q = h v", "q = h z | h a"),
        ("q = v v", "q = z | z a | a z | a"),
        ("q = w+ w- | v", "q = w+ w- | z | a"),
        ("q = v / a", "q = z | a"),
        ("q = v / a | h", "q = z"),
    ],
)
def test_a_bar_separates_alternatives(definition: str, final: str) -> None:
    assert final_definitions("p = g u d", "v = z | a", definition)[-1] == final


def test_the_members_have_the_form_madgraph_keeps() -> None:
    found = Multiparticles.from_definitions(["p = g u", "v = z | a", "vh = v h"])
    assert found.members == {
        "p": ["g", "u"],
        "v": [["z"], ["a"]],
        "vh": [["z", "h"], ["a", "h"]],
    }


def test_names_are_read_in_lower_case_unless_the_model_tells_them_apart() -> None:
    assert final_definitions("P = G U", "j = p") == ["p = g u", "j = g u"]
    case_sensitive = Multiparticles.from_definitions(
        ["P = G U", "j = p"], case_sensitive=True
    )
    assert case_sensitive.definitions() == ["P = G U", "j = p"]


@pytest.mark.parametrize(
    ("definitions", "problem"),
    [
        ([""], 'cannot read "define": it needs a label and at least one member'),
        (["p"], 'cannot read "define p": it needs a label and at least one member'),
        (["p ="], 'cannot read "define p =": it needs a member after "="'),
        (["p = g = u"], 'cannot read "define p = g = u": "=" may only follow'),
        (["= g u"], 'cannot read "define = g u": "=" may only follow the label'),
        (
            ["q = g / g", "r = q u"],
            'cannot read "define r = q u": a multiparticle without members',
        ),
    ],
)
def test_a_definition_that_madgraph_refuses_is_an_error(
    definitions: list[str], problem: str
) -> None:
    with pytest.raises(ValueError) as error:
        Multiparticles.from_definitions(definitions)
    assert problem in str(error.value)


def test_a_multiparticle_without_members_may_come_last() -> None:
    assert final_definitions("q = g / g", "r = u q")[-1] == "r = u"


def test_each_multiparticle_with_other_members_is_a_difference() -> None:
    found = Multiparticles.from_definitions(["p = g u", "j = g", "v = z | a"])
    reference = Multiparticles.from_definitions(["p = g u d", "lep = l+", "v = z | a"])
    assert [str(difference) for difference in found.differences(reference)] == [
        "unexpected define j: g",
        "missing define lep: l+",
        "define p: expected g u d, got g u",
    ]


def test_the_order_of_the_members_counts() -> None:
    found = Multiparticles.from_definitions(["p = u g"])
    reference = Multiparticles.from_definitions(["p = g u"])
    assert [str(difference) for difference in found.differences(reference)] == [
        "define p: expected g u, got u g"
    ]


def test_the_examples_of_the_documentation_hold() -> None:
    results = doctest.testmod(multiparticles)
    assert results.attempted > 0
    assert results.failed == 0
