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

HUGEPAGES_COMMAND = "grep -E 'HugePages_|Hugepagesize|Hugetlb' /proc/meminfo"


@dataclass
class HugePagesRecord:
    cluster: str
    host: str
    address: str
    collected_at: str
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
        return asdict(self)

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


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
    values = _parse_meminfo(output)
    total = values.get("HugePages_Total", 0)
    free = values.get("HugePages_Free", 0)
    used = max(total - free, 0)
    if total > 0:
        used_pct = round((used / total) * 100, 2)
        free_pct = round((free / total) * 100, 2)
        warning_level = _warning_level(total, free_pct)
    else:
        used_pct = 0.0
        free_pct = 0.0
        warning_level = "INFO"
    return HugePagesRecord(
        cluster=cluster,
        host=host,
        address=address,
        collected_at=collected_at,
        hugepages_total=total,
        hugepages_free=free,
        hugepages_rsvd=values.get("HugePages_Rsvd", 0),
        hugepages_surp=values.get("HugePages_Surp", 0),
        hugepagesize_kb=values.get("Hugepagesize", 0),
        hugetlb_kb=values.get("Hugetlb", 0),
        hugepages_used=used,
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


def _warning_level(total: int, free_pct: float) -> str:
    if total > 0 and free_pct <= 5:
        return "CRITICAL"
    if total > 0 and free_pct <= 10:
        return "WARNING"
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
