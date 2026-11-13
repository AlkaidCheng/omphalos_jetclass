from pathlib import Path

from omphjc.cli.formatting import (
    format_count,
    format_duration,
    format_fingerprint,
    format_job_line,
    format_row,
    format_size,
    format_usage,
)


def test_durations_change_unit_with_their_length() -> None:
    assert format_duration(0.0) == "0.0 s"
    assert format_duration(12.34) == "12.3 s"
    assert format_duration(65) == "1 min 05 s"
    assert format_duration(3599.4) == "59 min 59 s"
    assert format_duration(7620) == "2 h 07 min"


def test_sizes_use_binary_units() -> None:
    assert format_size(0) == "0 B"
    assert format_size(1023) == "1023 B"
    assert format_size(1024) == "1.0 KiB"
    assert format_size(3 * 2**20 + 2**19) == "3.5 MiB"
    assert format_size(2**30) == "1.0 GiB"
    assert format_size(2**41) == "2.0 TiB"


def test_a_fingerprint_shows_the_first_digits_of_its_hash() -> None:
    fingerprint = "lhe-v1:3f2a9c1e4b7d0000"
    assert format_fingerprint(fingerprint) == "lhe-v1:3f2a9c1e..."
    assert format_fingerprint("lhe-v1:3f2a9c1e") == "lhe-v1:3f2a9c1e"
    assert format_fingerprint("abc") == "abc"


def test_counts_take_the_plural() -> None:
    assert format_count(1, "folder") == "1 folder"
    assert format_count(0, "folder") == "0 folders"
    assert format_count(3, "folder") == "3 folders"


def test_usage_lists_what_was_recorded() -> None:
    assert format_usage({}) == "not recorded"
    assert format_usage({"wall_seconds": 1.5}) == "1.5 s wall"
    assert (
        format_usage(
            {"wall_seconds": 90, "cpu_seconds": 3600, "peak_memory_mib": 812.4}
        )
        == "1 min 30 s wall, 1 h 00 min CPU, 812 MiB peak"
    )


def test_a_row_puts_its_value_at_column_20() -> None:
    assert (
        format_row("log", "generate/run.log") == "  log               generate/run.log"
    )
    assert format_row("events", 100).index("100") == 20


def test_the_job_line_names_the_process_the_job_and_its_directory() -> None:
    assert (
        format_job_line("HToBB", 3, Path("runs/HToBB/job_3"))
        == "HToBB job 3: runs/HToBB/job_3"
    )
