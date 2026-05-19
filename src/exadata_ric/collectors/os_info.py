"""Operating system inventory collector."""
from __future__ import annotations
from .base import CollectionResult
from exadata_ric.config import HostConfig

class OsCollector:
    name = "os"
    def shell(self) -> str:
        return r'''
printf '===SECTION:hostname===\n'
if [ -r /etc/os-release ]; then . /etc/os-release; fi
printf 'hostname\t%s
' "$(hostname 2>/dev/null || printf unknown)"
printf 'fqdn\t%s
' "$(hostname -f 2>/dev/null || hostname 2>/dev/null || printf unknown)"
printf 'os_name\t%s
' "${PRETTY_NAME:-unknown}"
printf 'os_id\t%s
' "${ID:-unknown}"
printf 'os_version\t%s
' "${VERSION_ID:-unknown}"
printf 'kernel\t%s
' "$(uname -r 2>/dev/null || printf unknown)"
printf 'architecture\t%s
' "$(uname -m 2>/dev/null || printf unknown)"
printf 'uptime_seconds\t%s
' "$(cut -d' ' -f1 /proc/uptime 2>/dev/null | cut -d. -f1 || printf 0)"
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        row = {"environment": host.environment,"cluster": host.cluster,"host": host.name,"address": host.address,"ssh_user": host.ssh_user}
        for record in sections.get("hostname", []):
            if len(record) >= 2:
                row[record[0]] = record[1]
        return CollectionResult(self.name, [row])
