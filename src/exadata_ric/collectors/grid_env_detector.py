"""Grid Infrastructure environment detection collector."""
from __future__ import annotations
from .base import CollectionResult
from exadata_ric.config import HostConfig

class GridEnvDetectorCollector:
    name = "grid_env_detector"

    def shell(self) -> str:
        return r'''
printf '===SECTION:grid_env===\n'
grid_home="$(awk -F: '/^\+ASM|^-MGMTDB/ && $2 ~ /^\// {print $2; exit}' /etc/oratab 2>/dev/null)"
printf 'grid_home\t%s
' "${grid_home:-}"
if [ -n "$grid_home" ]; then export ORACLE_HOME="$grid_home"; export PATH="$ORACLE_HOME/bin:$PATH"; fi
printf 'crsctl_available\t%s
' "$(command -v crsctl >/dev/null 2>&1 && printf true || printf false)"
printf 'srvctl_available\t%s
' "$(command -v srvctl >/dev/null 2>&1 && printf true || printf false)"
printf 'grid_version\t%s
' "$(crsctl query crs activeversion 2>/dev/null | awk -F'[][]' 'NR==1{print $2}')"
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        row = {"environment": host.environment,"cluster": host.cluster,"host": host.name,"address": host.address,"ssh_user": host.ssh_user}
        for record in sections.get("grid_env", []):
            if len(record) >= 2:
                row[record[0]] = record[1]
        return CollectionResult(self.name, [row])
