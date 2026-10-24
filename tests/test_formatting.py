from omphjc.cli.formatting import count, describe_usage, duration, size


def test_durations_change_unit_with_their_length() -> None:
    assert duration(0.0) == "0.0 s"
    assert duration(12.34) == "12.3 s"
    assert duration(65) == "1 min 05 s"
    assert duration(3599.4) == "59 min 59 s"
    assert duration(7620) == "2 h 07 min"


def test_sizes_use_binary_units() -> None:
    assert size(0) == "0 B"
    assert size(1023) == "1023 B"
    assert size(1024) == "1.0 KiB"
    assert size(3 * 2**20 + 2**19) == "3.5 MiB"
    assert size(2**30) == "1.0 GiB"
    assert size(2**41) == "2.0 TiB"


def test_counts_take_the_plural() -> None:
    assert count(1, "folder") == "1 folder"
    assert count(0, "folder") == "0 folders"
    assert count(3, "folder") == "3 folders"


def test_usage_lists_what_was_recorded() -> None:
    assert describe_usage({}) == "not recorded"
    assert describe_usage({"wall_seconds": 1.5}) == "1.5 s wall"
    assert (
        describe_usage(
            {"wall_seconds": 90, "cpu_seconds": 3600, "max_memory_mb": 812.4}
        )
        == "1 min 30 s wall, 1 h 00 min CPU, 812 MiB peak"
    )
