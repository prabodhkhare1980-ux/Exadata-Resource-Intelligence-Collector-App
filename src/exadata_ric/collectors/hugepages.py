"""HugePages collector."""
from __future__ import annotations

from datetime import UTC, datetime

from .base import CollectionResult
from exadata_ric.config import HostConfig


class HugePagesCollector:
    name = "hugepages"

    def shell(self) -> str:
        return r"""
printf '===BEGIN_SECTION:hugepages===\n'
if [ "${HUGEPAGES_ENABLED:-true}" = "true" ]; then
  timeout "${HUGEPAGES_TIMEOUT_SECONDS:-15}s" grep -E 'HugePages_|Hugepagesize|Hugetlb' /proc/meminfo 2>&1
  hugepages_rc=$?
else
  printf 'hugepages_collection_error\thugepages_collection_disabled\n'
  hugepages_rc=126
fi
printf '===END_SECTION:hugepages===\n'
printf '===BEGIN_SECTION:hugepages_status===\n'
if [ "$hugepages_rc" -eq 0 ]; then
  printf 'collection_status\tsuccess\n'
elif [ "$hugepages_rc" -eq 126 ]; then
  printf 'collection_status\tskipped\n'
  printf 'collection_error\thugepages_collection_disabled\n'
else
  printf 'collection_status\tfailed\n'
  printf 'collection_error\tHugePages command exited with %s\n' "$hugepages_rc"
fi
printf '===END_SECTION:hugepages_status===\n'
"""

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        collected_at = datetime.now(UTC).isoformat(timespec="seconds")
        status = _status_value(sections, "collection_status") or "failed"
        error = _status_value(sections, "collection_error")
        values = _parse_meminfo(sections.get("hugepages", [])) if status == "success" else {}
        total = values.get("HugePages_Total", 0)
        free = values.get("HugePages_Free", 0)
        used = max(total - free, 0)
        if total > 0:
            used_pct = round((used / total) * 100, 2)
            free_pct = round((free / total) * 100, 2)
            warning = _warning_level(total, free_pct)
        else:
            used_pct = 0.0
            free_pct = 0.0
            warning = "INFO" if status == "success" else "ERROR"
        row = {
            "cluster": host.cluster,
            "host": host.name,
            "address": host.address,
            "collected_at": collected_at,
            "hugepages_total": total,
            "hugepages_free": free,
            "hugepages_rsvd": values.get("HugePages_Rsvd", 0),
            "hugepages_surp": values.get("HugePages_Surp", 0),
            "hugepagesize_kb": values.get("Hugepagesize", 0),
            "hugetlb_kb": values.get("Hugetlb", 0),
            "hugepages_used": used,
            "hugepages_used_pct": used_pct,
            "hugepages_free_pct": free_pct,
            "warning_level": warning,
            "collection_status": status,
            "collection_error": error,
        }
        return CollectionResult(self.name, [row])


def _parse_meminfo(records: list[list[str]]) -> dict[str, int]:
    values: dict[str, int] = {}
    for record in records:
        line = "\t".join(record)
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            values[key.strip()] = int(float(parts[0]))
        except ValueError:
            values[key.strip()] = 0
    return values


def _status_value(sections: dict[str, list[list[str]]], key: str) -> str:
    for record in sections.get("hugepages_status", []):
        if len(record) >= 2 and record[0] == key:
            return record[1].strip()
    return ""


def _warning_level(total: int, free_pct: float) -> str:
    if total > 0 and free_pct <= 5:
        return "CRITICAL"
    if total > 0 and free_pct <= 10:
        return "WARNING"
    return "OK"
