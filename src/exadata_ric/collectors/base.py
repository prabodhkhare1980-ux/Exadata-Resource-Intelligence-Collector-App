"""Collector interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from exadata_ric.config import HostConfig


@dataclass(frozen=True)
class CollectionResult:
    """Rows returned by a collector for one host."""

    name: str
    rows: list[dict[str, str | int | float | None]]


class Collector(Protocol):
    """Protocol implemented by all collectors."""

    name: str

    def shell(self) -> str:
        """Return POSIX shell that emits collector records."""

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        """Parse remote output sections into local records."""
