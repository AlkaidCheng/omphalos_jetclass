import omphjc


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(omphjc.__version__, str)
    assert omphjc.__version__
