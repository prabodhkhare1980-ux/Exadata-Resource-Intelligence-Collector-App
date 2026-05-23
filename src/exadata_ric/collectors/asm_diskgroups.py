"""ASM diskgroup collector."""
from __future__ import annotations

from .base import CollectionResult
from exadata_ric.config import HostConfig


class AsmDiskgroupCollector:
    name = "asm_diskgroups"

    def shell(self) -> str:
        return r'''
if [ "${ASM_ENABLED:-true}" != "true" ]; then
  printf '===BEGIN_SECTION:asm_status===\n'
  printf 'asm_collection_status\tskipped\n'
  printf 'asm_status\tskipped\n'
  printf '===END_SECTION:asm_status===\n'
else
printf '===BEGIN_SECTION:asm_grid_home===\n'
asm_grid_home="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"
printf 'grid_home\t%s\n' "${asm_grid_home:-}"
printf '===END_SECTION:asm_grid_home===\n'
printf '===BEGIN_SECTION:asm_status===\n'
if [ -z "$asm_grid_home" ]; then
  printf 'asm_collection_status\tskipped\n'
  printf 'asm_status\tskipped\n'
  printf '===END_SECTION:asm_status===\n'
else
  export ASM_COLLECTION_STATUS=success
  run_asm_cmd() {
    cmd_name="$1"; shift
    start_epoch="$(date +%s)"
    printf 'asm_command_start\t%s\t%s\n' "$cmd_name" "$start_epoch"
    output="$(sudo -n -u grid bash -c "export ORACLE_HOME='$asm_grid_home'; export PATH=\$ORACLE_HOME/bin:\$PATH; $*" 2>&1)"
    rc=$?
    end_epoch="$(date +%s)"
    duration="$((end_epoch-start_epoch))"
    printf 'asm_command_end\t%s\t%s\t%s\t%s\n' "$cmd_name" "$end_epoch" "$duration" "$rc"
    if [ "$rc" -ne 0 ]; then
      if [ "$ASM_COLLECTION_STATUS" = "success" ]; then ASM_COLLECTION_STATUS=partial; fi
      printf 'asm_warning\t%s\t%s\n' "$cmd_name" "command_failed_or_timed_out"
    fi
    printf '%s\n' "$output"
    return 0
  }
printf '===BEGIN_SECTION:asm_lsdg===\n'
run_asm_cmd asmcmd_lsdg "timeout ${ASM_TIMEOUT_SECONDS:-30}s asmcmd lsdg"
printf '===END_SECTION:asm_lsdg===\n'
printf '===BEGIN_SECTION:asm_lsdsk===\n'
run_asm_cmd asmcmd_lsdsk "timeout ${ASM_TIMEOUT_SECONDS:-30}s asmcmd lsdsk"
printf '===END_SECTION:asm_lsdsk===\n'
printf '===BEGIN_SECTION:asm_crs_dg===\n'
run_asm_cmd crsctl_stat_res "timeout ${ASM_TIMEOUT_SECONDS:-30}s crsctl stat res -t" | awk '/\.dg/ || /^asm_/'
printf '===END_SECTION:asm_crs_dg===\n'
  if [ "$ASM_COLLECTION_STATUS" = "partial" ]; then
    printf 'asm_collection_status\tpartial\n'
  else
    printf 'asm_collection_status\tsuccess\n'
  fi
  printf 'asm_status\t%s\n' "$ASM_COLLECTION_STATUS"
  printf '===END_SECTION:asm_status===\n'
fi
fi
'''

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        rows: list[dict[str, object]] = []
        status = "failed"
        for record in sections.get("asm_status", []):
            if len(record) >= 2 and record[0] == "asm_collection_status":
                status = record[1].strip() or "failed"
        for record in sections.get("asm_lsdg", []):
            line = "\t".join(record).strip()
            lower_line = line.lower()
            if (
                not line
                or line.startswith("ASM")
                or line.startswith("grid@")
                or line.startswith("$")
                or lower_line.startswith("state")
                or lower_line.startswith("asm_warning")
                or lower_line.startswith("asm_command_")
                or set(line) <= {"-", " "}
            ):
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
        rows.append(
            {
                "cluster": host.cluster,
                "host": host.name,
                "asm_collection_status": status,
            }
        )
        return CollectionResult(self.name, rows)

    def _to_int(self, value: str) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0
