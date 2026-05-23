"""ASM diskgroup collector."""
from __future__ import annotations

from .base import CollectionResult
from exadata_ric.config import HostConfig


class AsmDiskgroupCollector:
    name = "asm_diskgroups"

    def shell(self) -> str:
        return r'''
printf '===BEGIN_SECTION:asm_grid_home===\n'
asm_grid_home="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"
printf 'grid_home\t%s\n' "${asm_grid_home:-}"
printf '===END_SECTION:asm_grid_home===\n'
printf '===BEGIN_SECTION:asm_lsdg===\n'
if [ -n "$asm_grid_home" ]; then
  su - grid -c "export ORACLE_HOME='$asm_grid_home'; export PATH='\$ORACLE_HOME/bin:\$PATH'; asmcmd lsdg" 2>/dev/null
fi
printf '===END_SECTION:asm_lsdg===\n'
printf '===BEGIN_SECTION:asm_lsdsk===\n'
if [ -n "$asm_grid_home" ]; then
  su - grid -c "export ORACLE_HOME='$asm_grid_home'; export PATH='\$ORACLE_HOME/bin:\$PATH'; asmcmd lsdsk" 2>/dev/null
fi
printf '===END_SECTION:asm_lsdsk===\n'
printf '===BEGIN_SECTION:asm_crs_dg===\n'
if [ -n "$asm_grid_home" ]; then
  su - grid -c "export ORACLE_HOME='$asm_grid_home'; export PATH='\$ORACLE_HOME/bin:\$PATH'; crsctl stat res -t" 2>/dev/null | awk '/\.dg/{print}'
fi
printf '===END_SECTION:asm_crs_dg===\n'
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        rows: list[dict[str, object]] = []
        for record in sections.get("asm_lsdg", []):
            line = "\t".join(record).strip()
            if not line or line.lower().startswith("state") or set(line) <= {"-", " "}:
                continue
            parts = line.split()
            if len(parts) < 13:
                continue
            state = parts[0]
            dg_type = parts[1]
            total_mb = self._to_int(parts[6])
            free_mb = self._to_int(parts[7])
            usable_file_mb = self._to_int(parts[9])
            diskgroup_name = parts[12].rstrip("/")
            used_pct = round(((total_mb - free_mb) / total_mb) * 100, 2) if total_mb > 0 else 0.0
            risk = ""
            if used_pct >= 95:
                risk = "CRITICAL"
            elif used_pct >= 85:
                risk = "WARNING"
            rows.append(
                {
                    "cluster": host.cluster,
                    "host": host.name,
                    "diskgroup_name": diskgroup_name,
                    "state": state,
                    "type": dg_type,
                    "total_mb": total_mb,
                    "free_mb": free_mb,
                    "usable_file_mb": usable_file_mb,
                    "used_pct": used_pct,
                    "risk": risk,
                }
            )
        return CollectionResult(self.name, rows)

    def _to_int(self, value: str) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0
