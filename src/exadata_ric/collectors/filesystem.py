"""Filesystem capacity collector."""

from __future__ import annotations

from .base import CollectionResult
from exadata_ric.config import HostConfig


class FilesystemCollector:
    name = "filesystem"

    def shell(self) -> str:
        return r'''
printf 'SECTION	filesystem
'
df -P -B1 -T 2>/dev/null | awk 'NR > 1 && $2 != "tmpfs" && $2 != "devtmpfs" {print $1 "\t" $2 "\t" $3 "\t" $4 "\t" $5 "\t" $6 "\t" $7}'
printf 'END	filesystem
'
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        rows: list[dict[str, str | int | float | None]] = []
        for record in sections.get(self.name, []):
            if len(record) < 7:
                continue
            rows.append(
                {
                    "environment": host.environment,
                    "cluster": host.cluster,
                    "host": host.name,
                    "address": host.address,
                    "ssh_user": host.ssh_user,
                    "filesystem": record[0],
                    "fstype": record[1],
                    "size_bytes": _int(record[2]),
                    "used_bytes": _int(record[3]),
                    "available_bytes": _int(record[4]),
                    "use_percent": record[5],
                    "mountpoint": record[6],
                }
            )
        return CollectionResult(self.name, rows)


def _int(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value
