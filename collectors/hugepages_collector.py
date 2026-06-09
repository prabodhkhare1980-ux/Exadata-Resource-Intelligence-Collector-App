from __future__ import annotations

import logging
import shlex
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from collectors.shared_context import SharedHostContext
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig

THP_SENTINEL = "---THP---"

HUGEPAGES_COMMAND = (
    "grep -E '^MemTotal:|HugePages_|Hugepagesize|Hugetlb' /proc/meminfo; "
    f"echo '{THP_SENTINEL}'; "
    "cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || echo UNKNOWN"
)


@dataclass
class HugePagesRecord:
    cluster: str
    host: str
    address: str
    collected_at: str
    # New analytics-ready fields aligned with the documented schema.
    mem_total_gb: int = 0
    hp_size_kb: int = 0
    hp_total: int = 0
    hp_free: int = 0
    hp_rsvd: int = 0
    hp_surp: int = 0
    hp_used: int = 0
    hp_used_gb: int = 0
    hp_total_gb: int = 0
    hp_pct_of_memtotal: float = 0.0
    thp_status: str = "UNKNOWN"
    # Legacy fields retained for health-summary / failure-record callers.
    hugepages_total: int = 0
    hugepages_free: int = 0
    hugepages_rsvd: int = 0
    hugepages_surp: int = 0
    hugepagesize_kb: int = 0
    hugetlb_kb: int = 0
    hugepages_used: int = 0
    hugepages_used_pct: float = 0.0
    hugepages_free_pct: float = 0.0
    warning_level: str = "INFO"
    collection_status: str = "failed"
    collection_error: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return _public_schema_row(self)

    def to_json_dict(self) -> dict[str, object]:
        return _public_schema_row(self)


def _public_schema_row(record: "HugePagesRecord") -> dict[str, object]:
    """Return the analytics-ready row used by the CSV/JSON writers."""

    return {
        "Cluster": record.cluster,
        "Host": record.host,
        "MemTotal": record.mem_total_gb,
        "HP_Size_KB": record.hp_size_kb,
        "HP_Total": record.hp_total,
        "HP_Free": record.hp_free,
        "HP_Rsvd": record.hp_rsvd,
        "HP_Surp": record.hp_surp,
        "HP_Used": record.hp_used,
        "HP_Used_GB": record.hp_used_gb,
        "HP_Total_GB": record.hp_total_gb,
        "HP_Pct_of_MemTotal": record.hp_pct_of_memtotal,
        "THP_Status": record.thp_status,
        "Timestamp": record.collected_at,
    }


class HugePagesCollector:
    def __init__(self, runner: SSHRunner, context: SharedHostContext | None = None, logger: logging.Logger | None = None) -> None:
        self.runner = runner
        self.context = context
        self.logger = logger or logging.getLogger(__name__)

    def collect_host(
        self,
        cluster_name: str,
        host: "HostConfig",
        logger: logging.Logger,
        *,
        enabled: bool = True,
        timeout_seconds: int = 15,
    ) -> HugePagesRecord:
        logger.info("Starting HugePages collection for %s", host.name)
        collected_at = _utc_timestamp()
        if not enabled:
            logger.warning("HugePages collection skipped/failed for %s", host.name)
            return HugePagesRecord(
                cluster=cluster_name,
                host=host.name,
                address=host.address,
                collected_at=collected_at,
                collection_status="skipped",
                collection_error="hugepages_collection_disabled",
            )

        command = _with_timeout(HUGEPAGES_COMMAND, timeout_seconds)
        result = self._run_host_command(host, "hugepages_meminfo", command)
        if not result.ok:
            error = result.error or result.stderr.strip() or f"HugePages command exited with {result.returncode}"
            logger.warning("HugePages collection skipped/failed for %s", host.name)
            return HugePagesRecord(
                cluster=cluster_name,
                host=host.name,
                address=host.address,
                collected_at=collected_at,
                warning_level="ERROR",
                collection_status="failed",
                collection_error=error,
            )

        record = parse_hugepages_output(cluster_name, host.name, host.address, collected_at, result.stdout)
        logger.info("Completed HugePages collection for %s", host.name)
        return record

    def _run_host_command(self, host: "HostConfig", key: str, command: str):
        if self.context is not None:
            return self.context.run_cached(host, key, command)
        return self.runner.run_command(host, command)


def parse_hugepages_output(cluster: str, host: str, address: str, collected_at: str, output: str) -> HugePagesRecord:
    meminfo_text, separator, thp_text = output.partition(THP_SENTINEL)
    values = _parse_meminfo(meminfo_text)

    mem_total_kb = values.get("MemTotal", 0)
    hp_total = values.get("HugePages_Total", 0)
    hp_free = values.get("HugePages_Free", 0)
    hp_rsvd = values.get("HugePages_Rsvd", 0)
    hp_surp = values.get("HugePages_Surp", 0)
    hp_size_kb = values.get("Hugepagesize", 0)
    hugetlb_kb = values.get("Hugetlb", 0)
    hp_used = max(hp_total - hp_free, 0)

    mem_total_gb = int(round(mem_total_kb / 1024 / 1024)) if mem_total_kb else 0
    hp_used_gb = int(round(hp_used * hp_size_kb / 1024 / 1024)) if hp_size_kb else 0
    hp_total_gb = int(round(hp_total * hp_size_kb / 1024 / 1024)) if hp_size_kb else 0
    if mem_total_gb > 0:
        hp_pct_of_memtotal = round(hp_total_gb / mem_total_gb * 100, 1)
    else:
        hp_pct_of_memtotal = 0.0

    if hp_total > 0:
        used_pct = round((hp_used / hp_total) * 100, 2)
        free_pct = round((hp_free / hp_total) * 100, 2)
        warning_level = _warning_level(used_pct, hp_pct_of_memtotal)
    else:
        used_pct = 0.0
        free_pct = 0.0
        warning_level = "INFO"

    thp_status = thp_text.strip() if separator else ""
    if not thp_status:
        thp_status = "UNKNOWN"

    return HugePagesRecord(
        cluster=cluster,
        host=host,
        address=address,
        collected_at=collected_at,
        mem_total_gb=mem_total_gb,
        hp_size_kb=hp_size_kb,
        hp_total=hp_total,
        hp_free=hp_free,
        hp_rsvd=hp_rsvd,
        hp_surp=hp_surp,
        hp_used=hp_used,
        hp_used_gb=hp_used_gb,
        hp_total_gb=hp_total_gb,
        hp_pct_of_memtotal=hp_pct_of_memtotal,
        thp_status=thp_status,
        hugepages_total=hp_total,
        hugepages_free=hp_free,
        hugepages_rsvd=hp_rsvd,
        hugepages_surp=hp_surp,
        hugepagesize_kb=hp_size_kb,
        hugetlb_kb=hugetlb_kb,
        hugepages_used=hp_used,
        hugepages_used_pct=used_pct,
        hugepages_free_pct=free_pct,
        warning_level=warning_level,
        collection_status="success",
        collection_error="",
    )


def _parse_meminfo(output: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        values[key.strip()] = _to_int(parts[0])
    return values


def _warning_level(used_pct: float, alloc_pct_ram: float) -> str:
    if used_pct >= 95:
        return "CRITICAL"
    if used_pct >= 80:
        return "WARNING"
    if alloc_pct_ram and (alloc_pct_ram < 40 or alloc_pct_ram > 80):
        return "INFO"
    return "OK"


def _with_timeout(remote_command: str, timeout_seconds: int) -> str:
    return f"timeout {max(1, int(timeout_seconds))}s sh -c {shlex.quote(remote_command)}"


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
