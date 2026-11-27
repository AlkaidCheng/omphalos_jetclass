"""A card for the tests of the formats: ``name = value`` lines."""

from dataclasses import dataclass
from typing import ClassVar

from omphjc.comparison import Difference
from omphjc.formats.card import Card


@dataclass(frozen=True)
class SettingsCard(Card):
    """A card of ``name = value`` lines, with comments after ``#``."""

    format_name: ClassVar[str] = "settings"
    record_version: ClassVar[int] = 1

    settings: dict[str, str]

    @classmethod
    def from_text(cls, text: str) -> "SettingsCard":
        settings = {}
        for line in text.splitlines():
            name, separator, value = line.split("#", 1)[0].partition("=")
            if separator:
                settings[name.strip()] = value.strip()
        return cls(settings=settings)

    def content_record(self) -> dict[str, str]:
        return self.settings

    def differences(self, reference: "SettingsCard") -> list[Difference]:
        return Difference.between_mappings(self.settings, reference.settings)
