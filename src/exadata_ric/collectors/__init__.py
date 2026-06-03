"""Phase 1 collectors."""

from .asm_diskgroups import AsmDiskgroupCollector
from .base import Collector, CollectionResult
from .cpu_memory import CpuMemoryCollector
from .filesystem import FilesystemCollector
from .grid_env_detector import GridEnvDetectorCollector
from .hugepages import HugePagesCollector
from .os_info import OsCollector

PHASE1_COLLECTORS: tuple[Collector, ...] = (
    OsCollector(),
    GridEnvDetectorCollector(),
    AsmDiskgroupCollector(),
    HugePagesCollector(),
    CpuMemoryCollector(),
    FilesystemCollector(),
)

__all__ = [
    "CollectionResult",
    "Collector",
    "AsmDiskgroupCollector",
    "CpuMemoryCollector",
    "FilesystemCollector",
    "OsCollector",
    "GridEnvDetectorCollector",
    "HugePagesCollector",
    "PHASE1_COLLECTORS",
]
