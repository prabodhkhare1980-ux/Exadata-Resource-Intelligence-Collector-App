"""Phase 1 collectors."""

from .base import Collector, CollectionResult
from .cpu_memory import CpuMemoryCollector
from .filesystem import FilesystemCollector
from .os_info import OsCollector

PHASE1_COLLECTORS: tuple[Collector, ...] = (
    OsCollector(),
    CpuMemoryCollector(),
    FilesystemCollector(),
)

__all__ = [
    "CollectionResult",
    "Collector",
    "CpuMemoryCollector",
    "FilesystemCollector",
    "OsCollector",
    "PHASE1_COLLECTORS",
]
