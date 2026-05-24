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
  printf 'asm_collection_error\tasm_collection_disabled\n'
  printf 'asm_status\tskipped\n'
  printf '===END_SECTION:asm_status===\n'
else
asm_identity="$(awk -F: '/^\+ASM/ {print $1 "|" $2; exit}' /etc/oratab 2>/dev/null)"
asm_sid="${asm_identity%%|*}"
asm_grid_home="${asm_identity#*|}"
if [ "$asm_identity" = "$asm_grid_home" ]; then
  asm_sid=""
fi
asmcmd_path="${asm_grid_home}/bin/asmcmd"
grid_owner=""
if [ -n "$asm_grid_home" ] && [ -f "$asm_grid_home/bin/crsctl" ]; then
  grid_owner="$(stat -c '%U' "$asm_grid_home/bin/crsctl" 2>/dev/null)"
fi
if [ -z "$grid_owner" ] && [ -n "$asm_grid_home" ] && [ -f "$asmcmd_path" ]; then
  grid_owner="$(stat -c '%U' "$asmcmd_path" 2>/dev/null)"
fi

printf '===BEGIN_SECTION:asm_env===\n'
printf 'grid_home\t%s\n' "${asm_grid_home:-}"
printf 'grid_owner\t%s\n' "${grid_owner:-}"
printf 'asm_sid\t%s\n' "${asm_sid:-}"
printf 'asmcmd_path\t%s\n' "${asmcmd_path:-}"
printf '===END_SECTION:asm_env===\n'

printf 'ASM env resolved: host=%s grid_home=%s grid_owner=%s asm_sid=%s\n' "$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo unknown)" "${asm_grid_home:-}" "${grid_owner:-}" "${asm_sid:-}" >&2

printf '===BEGIN_SECTION:asm_status===\n'
if [ -z "$asm_grid_home" ] || [ -z "$asm_sid" ] || [ -z "$grid_owner" ] || [ ! -d "$asm_grid_home" ] || [ ! -f "$asmcmd_path" ]; then
  printf 'asm_collection_status\tfailed\n'
  printf 'asm_collection_error\tmissing_required_asm_environment\n'
  printf 'asm_status\tfailed\n'
  printf '===END_SECTION:asm_status===\n'
else
  asm_timeout="${ASM_TIMEOUT_SECONDS:-30}"
  printf '===BEGIN_SECTION:asm_lsdg===\n'
  asm_lsdg_output="$(sudo -n -u "$grid_owner" env ORACLE_HOME="$asm_grid_home" ORACLE_SID="$asm_sid" PATH="$asm_grid_home/bin:$PATH" timeout "${asm_timeout}s" asmcmd lsdg 2>&1)"
  asmcmd_rc=$?
  printf '%s\n' "$asm_lsdg_output"
  printf '===END_SECTION:asm_lsdg===\n'

  if [ "$asmcmd_rc" -ne 0 ]; then
    printf '===BEGIN_SECTION:asm_sqlplus_lsdg===\n'
    sqlplus_output="$(sudo -n -u "$grid_owner" env ORACLE_HOME="$asm_grid_home" ORACLE_SID="$asm_sid" PATH="$asm_grid_home/bin:$PATH" timeout "${asm_timeout}s" sqlplus -s / as sysasm <<'SQL' 2>&1
set pages 0 lines 200 feedback off verify off heading off echo off
select state||' '||type||' N 512 4096 4194304 '||total_mb||' '||free_mb||' 0 '||usable_file_mb||' 0 N '||name||'/' from v$asm_diskgroup;
exit
SQL
)"
    sqlplus_rc=$?
    printf '%s\n' "$sqlplus_output"
    printf '===END_SECTION:asm_sqlplus_lsdg===\n'
  else
    sqlplus_rc=0
  fi

  if [ "$asmcmd_rc" -eq 0 ]; then
    printf 'asm_collection_status\tsuccess\n'
    printf 'asm_status\tsuccess\n'
  elif [ "$sqlplus_rc" -eq 0 ]; then
    printf 'asm_collection_status\tpartial\n'
    printf 'asm_status\tpartial\n'
  else
    printf 'asm_collection_status\tfailed\n'
    printf 'asm_collection_error\tasmcmd_and_sqlplus_failed\n'
    printf 'asm_status\tfailed\n'
  fi
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
            warning_level = "OK"
            if used_pct >= 95:
                warning_level = "CRITICAL"
            elif used_pct >= 85:
                warning_level = "WARNING"
            rows.append(
                {
                    "cluster": host.cluster,
                    "host": host.name,
                    "address": host.address,
                    "diskgroup_name": diskgroup_name,
                    "state": state,
                    "type": dg_type,
                    "total_mb": total_mb,
                    "free_mb": free_mb,
                    "usable_file_mb": usable_file_mb,
                    "used_pct": used_pct,
                    "warning_level": warning_level,
                }
            )
        rows.append(
            {
                "cluster": host.cluster,
                "host": host.name,
                "address": host.address,
                "asm_collection_status": status,
                "grid_home": self._get_env_value(sections, "grid_home"),
                "grid_owner": self._get_env_value(sections, "grid_owner"),
                "asm_sid": self._get_env_value(sections, "asm_sid"),
                "asmcmd_path": self._get_env_value(sections, "asmcmd_path"),
                "asm_collection_error": self._get_status_value(sections, "asm_collection_error"),
            }
        )
        return CollectionResult(self.name, rows)

    def _get_env_value(self, sections: dict[str, list[list[str]]], key: str) -> str:
        for record in sections.get("asm_env", []):
            if len(record) >= 2 and record[0] == key:
                return record[1].strip()
        return ""

    def _get_status_value(self, sections: dict[str, list[list[str]]], key: str) -> str:
        for record in sections.get("asm_status", []):
            if len(record) >= 2 and record[0] == key:
                return record[1].strip()
        return ""

    def _to_int(self, value: str) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0
