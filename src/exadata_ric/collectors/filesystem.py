"""Filesystem capacity collector."""

from __future__ import annotations

from .base import CollectionResult
from exadata_ric.config import HostConfig


class FilesystemCollector:
    name = "filesystem"

    def shell(self) -> str:
        return r'''
printf '===BEGIN_SECTION:df===\n'
df -P -B1 -T 2>/dev/null | awk 'NR > 1 && $2 != "tmpfs" && $2 != "devtmpfs" {print $1 "\t" $2 "\t" $3 "\t" $4 "\t" $5 "\t" $6 "\t" $7}'
printf '===END_SECTION:df===\n'
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        rows: list[dict[str, str | int | float | None]] = []
        for record in sections.get("df", []):
            if len(record) < 7:
                continue
            pct = str(record[5]).rstrip("%")
            use_pct = _int(pct)
            risk = "OK"
            if isinstance(use_pct, int) and use_pct > 95:
                risk = "CRITICAL"
            elif isinstance(use_pct, int) and use_pct > 85:
                risk = "WARNING"
            rows.append({"environment": host.environment,"cluster": host.cluster,"host": host.name,"address": host.address,"ssh_user": host.ssh_user,"filesystem": record[0],"fstype": record[1],"size_bytes": _int(record[2]),"used_bytes": _int(record[3]),"available_bytes": _int(record[4]),"use_percent": record[5],"mountpoint": record[6],"risk_flag": risk})
        return CollectionResult(self.name, rows)


def _int(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value
