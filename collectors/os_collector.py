"""Operating system collector for Exadata and RAC nodes."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import ClusterConfig, HostConfig

SECTION_PREFIX = "__ERIC_SECTION__:"


@dataclass
class OSCollectionRecord:
    """Normalized Phase 1 OS collection result for one host."""

    cluster: str
    host: str
    address: str
    collected_at: str
    status: str
    error: str = ""
    ssh_returncode: int | None = None
    hostname: str = ""
    uptime: str = ""
    filesystems: list[dict[str, str]] = field(default_factory=list)
    free_mb: dict[str, str] = field(default_factory=dict)
    cpu: dict[str, str] = field(default_factory=dict)
    meminfo: dict[str, str] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)

    def to_csv_row(self) -> dict[str, str]:
        """Flatten the record for CSV output while preserving detail as JSON strings."""

        return {
            "cluster": self.cluster,
            "host": self.host,
            "address": self.address,
            "collected_at": self.collected_at,
            "status": self.status,
            "error": self.error,
            "ssh_returncode": "" if self.ssh_returncode is None else str(self.ssh_returncode),
            "hostname": self.hostname,
            "uptime": self.uptime,
            "filesystems_json": json.dumps(self.filesystems, sort_keys=True),
            "free_mb_json": json.dumps(self.free_mb, sort_keys=True),
            "cpu_json": json.dumps(self.cpu, sort_keys=True),
            "meminfo_json": json.dumps(self.meminfo, sort_keys=True),
        }

    def to_json_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""

        return asdict(self)


class OSCollector:
    """Collect Phase 1 OS, filesystem, CPU, and memory data from remote hosts."""

    def __init__(self, runner: SSHRunner, logger: logging.Logger | None = None) -> None:
        self.runner = runner
        self.logger = logger or logging.getLogger(__name__)

    def collect_cluster(
        self,
        cluster: "ClusterConfig",
        host_loggers: dict[str, logging.Logger] | None = None,
    ) -> list[OSCollectionRecord]:
        """Collect OS inventory from every host in a cluster with per-host isolation."""

        records: list[OSCollectionRecord] = []
        for host in cluster.hosts:
            logger = (host_loggers or {}).get(host.name, self.logger)
            try:
                records.append(self.collect_host(cluster.name, host, logger))
            except Exception as exc:  # noqa: BLE001 - keep collection moving per host.
                logger.exception("Unhandled collection failure for %s", host.name)
                records.append(
                    OSCollectionRecord(
                        cluster=cluster.name,
                        host=host.name,
                        address=host.address,
                        collected_at=_utc_now(),
                        status="failed",
                        error=f"Unhandled collection failure: {exc}",
                    )
                )
        return records

    def collect_host(
        self, cluster_name: str, host: "HostConfig", logger: logging.Logger
    ) -> OSCollectionRecord:
        """Collect OS data from a single host."""

        logger.info("Starting OS collection for %s (%s)", host.name, host.address)
        result = self.runner.run_script(host, OS_COLLECTION_SCRIPT)
        collected_at = _utc_now()

        if not result.ok:
            error = result.error or result.stderr.strip() or f"SSH exited with {result.returncode}"
            error_lower = error.lower()
            if "permission denied" in error_lower:
                error = (
                    f"{error}\nManual test:\nssh -i <private_key> {host.user}@{host.address} hostname"
                )
            elif "host key verification failed" in error_lower:
                error = (
                    f"{error}\nManual test:\nssh -i <private_key> {host.user}@{host.address} hostname\nThen type yes once."
                )
            logger.error("Collection failed for %s: %s", host.name, error)
            return OSCollectionRecord(
                cluster=cluster_name,
                host=host.name,
                address=host.address,
                collected_at=collected_at,
                status="failed",
                error=error,
                ssh_returncode=result.returncode,
                raw={"stdout": result.stdout, "stderr": result.stderr},
            )

        sections = _parse_sections(result.stdout)
        record = OSCollectionRecord(
            cluster=cluster_name,
            host=host.name,
            address=host.address,
            collected_at=collected_at,
            status="ok",
            ssh_returncode=result.returncode,
            hostname=sections.get("hostname", "").strip().splitlines()[0:1][0]
            if sections.get("hostname", "").strip()
            else "",
            uptime=sections.get("uptime", "").strip().replace("\n", " | "),
            filesystems=_parse_df(sections.get("df", "")),
            free_mb=_parse_keyed_table(sections.get("free", "")),
            cpu=_parse_colon_map(sections.get("lscpu", "")),
            meminfo=_parse_colon_map(sections.get("meminfo", "")),
            raw=sections,
        )
        logger.info("Completed OS collection for %s", host.name)
        return record


OS_COLLECTION_SCRIPT = r"""
set -o pipefail
emit_section() {
  printf '\n__ERIC_SECTION__:%s\n' "$1"
}

emit_section hostname
(hostname -f 2>/dev/null || hostname 2>/dev/null) || true

emit_section uptime
(uptime -p 2>/dev/null || uptime 2>/dev/null) || true

emit_section df
df -hPT 2>/dev/null || true

emit_section free
free -m 2>/dev/null || true

emit_section lscpu
lscpu 2>/dev/null || true

emit_section meminfo
cat /proc/meminfo 2>/dev/null || true
""".lstrip()


def _parse_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in output.splitlines():
        if line.startswith(SECTION_PREFIX):
            current = line.removeprefix(SECTION_PREFIX).strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)

    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _parse_df(output: str) -> list[dict[str, str]]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return []

    filesystems: list[dict[str, str]] = []
    for line in lines[1:]:
        parts = line.split(maxsplit=6)
        if len(parts) < 7:
            continue
        filesystems.append(
            {
                "filesystem": parts[0],
                "type": parts[1],
                "size": parts[2],
                "used": parts[3],
                "available": parts[4],
                "use_percent": parts[5],
                "mounted_on": parts[6],
            }
        )
    return filesystems


def _parse_keyed_table(output: str) -> dict[str, str]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return {}

    headers = lines[0].split()
    parsed: dict[str, str] = {}
    for line in lines[1:]:
        label, _, remainder = line.partition(":")
        values = remainder.split() if remainder else line.split()[1:]
        for header, value in zip(headers, values, strict=False):
            parsed[f"{label.lower()}_{header.lower()}"] = value
    return parsed


def _parse_colon_map(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower().replace(" ", "_")
        parsed[normalized_key] = value.strip()
    return parsed


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
