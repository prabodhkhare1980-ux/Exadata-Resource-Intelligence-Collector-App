"""Phase 1 collectors."""

from .base import Collector, CollectionResult
from .cpu_memory import CpuMemoryCollector
from .filesystem import FilesystemCollector
from .grid_env_detector import GridEnvDetectorCollector
from .os_info import OsCollector

PHASE1_COLLECTORS: tuple[Collector, ...] = (
    OsCollector(),
    CpuMemoryCollector(),
    FilesystemCollector(),
    GridEnvDetectorCollector(),
)

__all__ = [
    "CollectionResult",
    "Collector",
    "CpuMemoryCollector",
    "FilesystemCollector",
    "OsCollector",
    "GridEnvDetectorCollector",
    "PHASE1_COLLECTORS",
]
