"""Operating system inventory collector."""

from __future__ import annotations

from .base import CollectionResult
from exadata_ric.config import HostConfig


class OsCollector:
    name = "os"

    def shell(self) -> str:
        return r'''
printf 'SECTION	os
'
if [ -r /etc/os-release ]; then . /etc/os-release; fi
printf 'hostname	%s
' "$(hostname 2>/dev/null || printf unknown)"
printf 'fqdn	%s
' "$(hostname -f 2>/dev/null || hostname 2>/dev/null || printf unknown)"
printf 'os_name	%s
' "${PRETTY_NAME:-unknown}"
printf 'os_id	%s
' "${ID:-unknown}"
printf 'os_version	%s
' "${VERSION_ID:-unknown}"
printf 'kernel	%s
' "$(uname -r 2>/dev/null || printf unknown)"
printf 'architecture	%s
' "$(uname -m 2>/dev/null || printf unknown)"
printf 'uptime_seconds	%s
' "$(cut -d' ' -f1 /proc/uptime 2>/dev/null | cut -d. -f1 || printf 0)"
printf 'END	os
'
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        row: dict[str, str | int | float | None] = _host_row(host)
        for record in sections.get(self.name, []):
            if len(record) >= 2:
                row[record[0]] = record[1]
        return CollectionResult(self.name, [row])


def _host_row(host: HostConfig) -> dict[str, str | int | float | None]:
    return {
        "environment": host.environment,
        "cluster": host.cluster,
        "host": host.name,
        "address": host.address,
        "ssh_user": host.ssh_user,
    }
