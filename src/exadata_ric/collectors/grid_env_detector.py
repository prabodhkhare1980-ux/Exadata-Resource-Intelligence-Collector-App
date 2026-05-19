"""Grid/Oracle inventory collector."""
from __future__ import annotations

import re

from .base import CollectionResult
from exadata_ric.config import HostConfig


_INSTANCE_STATUS = re.compile(r"^Instance\s+([A-Za-z0-9_$#]+)\s+is\s+(running|not running)(?:\s+on\s+node\s+(.+))?$", re.IGNORECASE)
_DB_UNIQUE_NAME = re.compile(r"^[A-Za-z0-9_$#]+$")


class GridEnvDetectorCollector:
    name = "grid_env_detector"

    def shell(self) -> str:
        return r'''
printf '===BEGIN_SECTION:grid_env===\n'
grid_home="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"
printf 'grid_home\t%s
' "${grid_home:-}"
if [ -n "$grid_home" ]; then export ORACLE_HOME="$grid_home"; export PATH="$ORACLE_HOME/bin:$PATH"; fi
printf 'crsctl_available\t%s
' "$(command -v crsctl >/dev/null 2>&1 && printf true || printf false)"
printf 'srvctl_available\t%s
' "$(command -v srvctl >/dev/null 2>&1 && printf true || printf false)"
printf 'gi_version\t%s
' "$(crsctl query crs activeversion 2>/dev/null | awk -F'[][]' 'NR==1{print $2}')"
printf '===END_SECTION:grid_env===\n'
printf '===BEGIN_SECTION:srvctl_databases===\n'
srvctl config database 2>/dev/null | awk 'NF {print "db_unique_name\t" $0}'
printf '===END_SECTION:srvctl_databases===\n'
printf '===BEGIN_SECTION:srvctl_details===\n'
srvctl config database 2>/dev/null | while IFS= read -r db_name; do
  [ -n "$db_name" ] || continue
  printf 'db_unique_name\t%s\n' "$db_name"
  printf 'config_raw\t%s\n' "$(srvctl config database -d "$db_name" 2>&1 | tr '\n' '|' | sed 's/|$//')"
  printf 'status_raw\t%s\n' "$(srvctl status database -d "$db_name" 2>&1 | tr '\n' '|' | sed 's/|$//')"
done
printf '===END_SECTION:srvctl_details===\n'
printf '===BEGIN_SECTION:pmon_raw===\n'
ps -eo user,pid,ppid,lstart,cmd | grep '[o]ra_pmon_'
printf '===END_SECTION:pmon_raw===\n'
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        row = {"environment": host.environment, "cluster": host.cluster, "host": host.name, "address": host.address, "ssh_user": host.ssh_user}
        for record in sections.get("grid_env", []):
            if len(record) >= 2:
                row[record[0]] = record[1]

        db_names = [
            record[1].strip()
            for record in sections.get("srvctl_databases", [])
            if len(record) >= 2
            and record[0] == "db_unique_name"
            and record[1].strip()
            and _DB_UNIQUE_NAME.fullmatch(record[1].strip())
        ]
        details_by_db = self._parse_srvctl_details(sections.get("srvctl_details", []))
        db_entries: list[dict[str, object]] = []
        instance_map: dict[str, str] = {}
        for db_name in db_names:
            detail = details_by_db.get(db_name, {})
            status_raw = str(detail.get("status_raw", ""))
            instances = self._parse_instances_from_status(status_raw)
            for inst in instances:
                instance_map[inst["instance_name"]] = db_name
            db_entries.append(
                {
                    "db_unique_name": db_name,
                    "config_raw": detail.get("config_raw", ""),
                    "status_raw": status_raw,
                    "instances": instances,
                }
            )

        pmon_instances = []
        for record in sections.get("pmon_raw", []):
            line = "\t".join(record)
            match = re.search(r"ora_pmon_([A-Za-z0-9_$#]+)", line)
            if not match:
                continue
            sid = match.group(1)
            columns = line.split(None, 6)
            os_user = columns[0] if len(columns) >= 1 else ""
            pid = columns[1] if len(columns) >= 2 else ""
            mapped_db = instance_map.get(sid)
            pmon_instances.append(
                {
                    "sid": sid,
                    "os_user": os_user,
                    "pid": pid,
                    "mapped_db_unique_name": mapped_db,
                    "mapping_source": "srvctl_status" if mapped_db else "unmapped",
                }
            )

        row["oracle_inventory"] = {
            "grid_home": row.get("grid_home", ""),
            "gi_version": row.get("gi_version", ""),
            "srvctl_databases": db_entries,
            "pmon_instances": pmon_instances,
        }
        row["srvctl_databases"] = db_entries
        row["pmon_instances"] = pmon_instances

        return CollectionResult(self.name, [row])

    def _parse_srvctl_details(self, records: list[list[str]]) -> dict[str, dict[str, str]]:
        details: dict[str, dict[str, str]] = {}
        current_db: str | None = None
        for record in records:
            if len(record) < 2:
                continue
            key, value = record[0], record[1]
            if key == "db_unique_name":
                current_db = value.strip()
                if not _DB_UNIQUE_NAME.fullmatch(current_db):
                    current_db = None
                    continue
                details.setdefault(current_db, {})
                continue
            if current_db and key in {"config_raw", "status_raw"}:
                details[current_db][key] = value.strip()
        return details

    def _parse_instances_from_status(self, status_raw: str) -> list[dict[str, str]]:
        instances: list[dict[str, str]] = []
        for line in [part.strip() for part in status_raw.split("|") if part.strip()]:
            match = _INSTANCE_STATUS.match(line)
            if not match:
                continue
            instance_name = match.group(1)
            state = match.group(2).lower()
            node = (match.group(3) or "").strip()
            instances.append({"instance_name": instance_name, "node": node, "state": state})
        return instances
