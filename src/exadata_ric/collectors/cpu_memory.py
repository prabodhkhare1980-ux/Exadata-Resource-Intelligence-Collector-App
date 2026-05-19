"""CPU and memory capacity collector."""

from __future__ import annotations

from .base import CollectionResult
from exadata_ric.config import HostConfig


class CpuMemoryCollector:
    name = "cpu_memory"

    def shell(self) -> str:
        return r'''
printf '===BEGIN_SECTION:lscpu===\n'
printf 'cpu_count\t%s
' "$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || printf 0)"
printf 'load_1m\t%s
' "$(awk '{print $1}' /proc/loadavg 2>/dev/null || printf 0)"
printf 'load_5m\t%s
' "$(awk '{print $2}' /proc/loadavg 2>/dev/null || printf 0)"
printf 'load_15m\t%s
' "$(awk '{print $3}' /proc/loadavg 2>/dev/null || printf 0)"
printf '===BEGIN_SECTION:meminfo===\n'
printf 'mem_total_kb\t%s
' "$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || printf 0)"
printf 'mem_available_kb\t%s
' "$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || printf 0)"
printf 'swap_total_kb\t%s
' "$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo 2>/dev/null || printf 0)"
printf 'swap_free_kb\t%s
' "$(awk '/^SwapFree:/ {print $2}' /proc/meminfo 2>/dev/null || printf 0)"
printf '===BEGIN_SECTION:free===\n'
printf '===END_SECTION:lscpu===\n'
printf '===END_SECTION:meminfo===\n'
free -m 2>/dev/null | awk 'NR==2{print "mem_total_mb\t"$2"\nmem_used_mb\t"$3"\nmem_free_mb\t"$4"\nmem_available_mb\t"$7} NR==3{print "swap_total_mb\t"$2"\nswap_used_mb\t"$3}'
printf '===END_SECTION:free===\n'
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        row: dict[str, str | int | float | None] = {
            "environment": host.environment,
            "cluster": host.cluster,
            "host": host.name,
            "address": host.address,
            "ssh_user": host.ssh_user,
        }
        for section in ("lscpu", "meminfo", "free"):
            for record in sections.get(section, []):
                if len(record) >= 2:
                    row[record[0]] = _number(record[1])
        return CollectionResult(self.name, [row])


def _number(value: str) -> int | float | str:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value
