"""The text the commands print for durations, byte sizes, counts and a stage's usage."""

from collections.abc import Mapping


def describe_usage(usage: Mapping[str, float]) -> str:
    """Return a stage's wall time, CPU time and peak memory in one line."""
    parts = []
    if "wall_seconds" in usage:
        parts.append(f"{duration(usage['wall_seconds'])} wall")
    if "cpu_seconds" in usage:
        parts.append(f"{duration(usage['cpu_seconds'])} CPU")
    if "max_memory_mb" in usage:
        parts.append(f"{usage['max_memory_mb']:.0f} MiB peak")
    return ", ".join(parts) if parts else "not recorded"


def duration(seconds: float) -> str:
    """Return `seconds` as ``12.3 s``, ``4 min 05 s`` or ``2 h 07 min``."""
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes} min {rest:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def size(n_bytes: int) -> str:
    """Return `n_bytes` as ``512 B``, ``3.4 KiB``, ``1.2 GiB``."""
    if n_bytes < 1024:
        return f"{n_bytes} B"
    scaled = n_bytes / 1024
    for unit in ("KiB", "MiB", "GiB"):
        if scaled < 1024:
            return f"{scaled:.1f} {unit}"
        scaled /= 1024
    return f"{scaled:.1f} TiB"


def count(number: int, noun: str) -> str:
    """Return ``1 folder`` or ``3 folders``."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"
