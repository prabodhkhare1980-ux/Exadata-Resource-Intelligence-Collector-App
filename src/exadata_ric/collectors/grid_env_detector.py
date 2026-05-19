"""Grid/Oracle inventory collector."""
from __future__ import annotations

import re
from .base import CollectionResult
from exadata_ric.config import HostConfig


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
printf '===BEGIN_SECTION:pmon_raw===\n'
ps -eo user,pid,ppid,lstart,cmd | awk '/[o]ra_pmon_/ {print $0}'
printf '===END_SECTION:pmon_raw===\n'
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        row = {"environment": host.environment, "cluster": host.cluster, "host": host.name, "address": host.address, "ssh_user": host.ssh_user}
        for record in sections.get("grid_env", []):
            if len(record) >= 2:
                row[record[0]] = record[1]

        row["srvctl_databases"] = [
            {"db_unique_name": record[1].strip(), "source": "srvctl"}
            for record in sections.get("srvctl_databases", [])
            if len(record) >= 2 and record[0] == "db_unique_name"
        ]

        pmon_instances = []
        for record in sections.get("pmon_raw", []):
            line = "\t".join(record)
            match = re.search(r"ora_pmon_([A-Za-z0-9_$#]+)", line)
            if match:
                pmon_instances.append({"sid": match.group(1), "mapping_source": "runtime_evidence"})
        row["pmon_instances"] = pmon_instances

        return CollectionResult(self.name, [row])
