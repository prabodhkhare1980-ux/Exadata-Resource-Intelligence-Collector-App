"""CPU and memory capacity collector."""

from __future__ import annotations

from .base import CollectionResult
from exadata_ric.config import HostConfig


class CpuMemoryCollector:
    name = "cpu_memory"

    def shell(self) -> str:
        return r'''
printf 'SECTION	cpu_memory
'
printf 'cpu_count	%s
' "$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || printf 0)"
printf 'load_1m	%s
' "$(awk '{print $1}' /proc/loadavg 2>/dev/null || printf 0)"
printf 'load_5m	%s
' "$(awk '{print $2}' /proc/loadavg 2>/dev/null || printf 0)"
printf 'load_15m	%s
' "$(awk '{print $3}' /proc/loadavg 2>/dev/null || printf 0)"
printf 'mem_total_kb	%s
' "$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || printf 0)"
printf 'mem_available_kb	%s
' "$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || printf 0)"
printf 'swap_total_kb	%s
' "$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo 2>/dev/null || printf 0)"
printf 'swap_free_kb	%s
' "$(awk '/^SwapFree:/ {print $2}' /proc/meminfo 2>/dev/null || printf 0)"
printf 'END	cpu_memory
'
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        row: dict[str, str | int | float | None] = {
            "environment": host.environment,
            "cluster": host.cluster,
            "host": host.name,
            "address": host.address,
            "ssh_user": host.ssh_user,
        }
        for record in sections.get(self.name, []):
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
