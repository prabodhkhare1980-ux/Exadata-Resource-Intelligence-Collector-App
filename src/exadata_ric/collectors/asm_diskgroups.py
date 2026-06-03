"""ASM diskgroup collector."""
from __future__ import annotations

from datetime import UTC, datetime

from .base import CollectionResult
from exadata_ric.config import HostConfig


class AsmDiskgroupCollector:
    name = "asm_diskgroups"

    def shell(self) -> str:
        return r"""
if [ "${ASM_ENABLED:-true}" != "true" ]; then
  printf '===BEGIN_SECTION:asm_status===\n'
  printf 'asm_collection_status\tskipped\n'
  printf 'asm_collection_error\tasm_collection_disabled\n'
  printf 'asm_status\tskipped\n'
  printf '===END_SECTION:asm_status===\n'
else
asm_timeout="${ASM_TIMEOUT_SECONDS:-30}"
asm_identity="$(timeout "${asm_timeout}s" awk -F: '/^\+ASM/ {print $1 "|" $2; exit}' /etc/oratab 2>/dev/null)"
asm_sid="${asm_identity%%|*}"
asm_grid_home="${asm_identity#*|}"
if [ "$asm_identity" = "$asm_grid_home" ]; then
  asm_sid=""
fi
grid_owner_identity="$(timeout "${asm_timeout}s" ps -eo user,args 2>/dev/null | awk '/[p]mon_\+ASM/ {print $1 "|" $NF; exit}')"
grid_owner="${grid_owner_identity%%|*}"
asmcmd_path="${asm_grid_home}/bin/asmcmd"

printf '===BEGIN_SECTION:asm_env===\n'
printf 'grid_home\t%s\n' "${asm_grid_home:-}"
printf 'grid_owner\t%s\n' "${grid_owner:-}"
printf 'asm_sid\t%s\n' "${asm_sid:-}"
printf 'asmcmd_path\t%s\n' "${asmcmd_path:-}"
printf '===END_SECTION:asm_env===\n'

printf '===BEGIN_SECTION:asm_lsdg===\n'
if [ -n "$asm_grid_home" ] && [ -n "$asm_sid" ] && [ -n "$grid_owner" ]; then
  sudo -n -u "$grid_owner" env ORACLE_HOME="$asm_grid_home" ORACLE_SID="$asm_sid" PATH="$asm_grid_home/bin:/usr/bin:/bin" timeout "${asm_timeout}s" asmcmd lsdg 2>&1
  asmcmd_rc=$?
else
  asmcmd_rc=127
fi
printf '===END_SECTION:asm_lsdg===\n'

printf '===BEGIN_SECTION:asm_status===\n'
if [ "$asmcmd_rc" -eq 0 ]; then
  printf 'asm_collection_status\tsuccess\n'
  printf 'asm_status\tsuccess\n'
elif [ -z "$asm_grid_home" ] || [ -z "$asm_sid" ] || [ -z "$grid_owner" ]; then
  printf 'asm_collection_status\tfailed\n'
  printf 'asm_collection_error\tmissing_required_asm_environment\n'
  printf 'asm_status\tfailed\n'
else
  printf 'asm_collection_status\tfailed\n'
  printf 'asm_collection_error\tasmcmd_failed\n'
  printf 'asm_status\tfailed\n'
fi
printf '===END_SECTION:asm_status===\n'
fi
"""

    def parse(self, host: HostConfig, sections: dict[str, list[list[str]]]) -> CollectionResult:
        status = "failed"
        for record in sections.get("asm_status", []):
            if len(record) >= 2 and record[0] == "asm_collection_status":
                status = record[1].strip() or "failed"

        collected_at = datetime.now(UTC).isoformat(timespec="seconds")
        env = {
            "record_type": "diskgroup",
            "collected_at": collected_at,
            "asm_collection_status": status,
            "grid_home": self._get_env_value(sections, "grid_home"),
            "grid_owner": self._get_env_value(sections, "grid_owner"),
            "asm_sid": self._get_env_value(sections, "asm_sid"),
            "asmcmd_path": self._get_env_value(sections, "asmcmd_path"),
        }
        if status != "success":
            env["asm_collection_error"] = self._get_status_value(sections, "asm_collection_error")
        asm_lsdg_records = sections.get("asm_lsdg", [])
        rows = self._parse_asmcmd_rows(host, asm_lsdg_records, env)
        metadata = {
            "cluster": host.cluster,
            "host": host.name,
            "address": host.address,
            "record_type": "host_metadata",
            "collected_at": collected_at,
            "asm_collection_status": status,
            "grid_home": env["grid_home"],
            "grid_owner": env["grid_owner"],
            "asm_sid": env["asm_sid"],
            "asmcmd_path": env["asmcmd_path"],
            "asmcmd_stdout": "\n".join("\t".join(record) for record in asm_lsdg_records),
            "asmcmd_stderr": "",
        }
        return CollectionResult(self.name, [metadata, *rows])

    def _parse_asmcmd_rows(
        self, host: HostConfig, records: list[list[str]], env: dict[str, str]
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        header: list[str] | None = None
        for record in records:
            line = "\t".join(record).strip()
            lower_line = line.lower()
            if (
                not line
                or line.startswith("ASM")
                or line.startswith("grid@")
                or line.startswith("$")
                or lower_line.startswith("asm_warning")
                or lower_line.startswith("asm_command_")
                or set(line) <= {"-", " "}
            ):
                continue
            parts = line.split()
            if parts and parts[0].lower() == "state":
                header = parts
                continue
            if not header:
                continue
            values = self._asmcmd_values_from_columns(header, parts)
            diskgroup_name = str(values["name"])
            total_mb = int(values["total_mb"])
            free_mb = int(values["free_mb"])
            usable_file_mb = int(values["usable_file_mb"])
            if not diskgroup_name or total_mb <= 0:
                continue
            total_tb = round(total_mb / 1024 / 1024, 2)
            free_tb = round(free_mb / 1024 / 1024, 2)
            usable_tb = round(usable_file_mb / 1024 / 1024, 2)
            free_pct = round((free_mb / total_mb) * 100, 2)
            usable_pct = round((usable_file_mb / total_mb) * 100, 2)
            used_pct = round(((total_mb - free_mb) / total_mb) * 100, 2)
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
                    "state": values["state"],
                    "type": values["type"],
                    "total_mb": total_mb,
                    "free_mb": free_mb,
                    "usable_file_mb": usable_file_mb,
                    "total_tb": total_tb,
                    "free_tb": free_tb,
                    "usable_tb": usable_tb,
                    "free_pct": free_pct,
                    "usable_pct": usable_pct,
                    "used_pct": used_pct,
                    "warning_level": warning_level,
                    **env,
                }
            )
        return rows

    def _asmcmd_values_from_columns(self, header: list[str], parts: list[str]) -> dict[str, object]:
        header_lookup = {name.lower(): index for index, name in enumerate(header)}
        au_index = header_lookup.get("au")
        req_index = header_lookup.get("req_mir_free_mb")
        return {
            "name": parts[-1].rstrip("/") if parts else "",
            "state": parts[0] if len(parts) > 0 else "",
            "type": parts[1] if len(parts) > 1 else "",
            "total_mb": self._to_int(self._part_after(parts, au_index, 1)),
            "free_mb": self._to_int(self._part_after(parts, au_index, 2)),
            "usable_file_mb": self._to_int(self._part_after(parts, req_index, 1)),
        }

    def _part_after(self, parts: list[str], index: int | None, offset: int) -> str:
        if index is None:
            return "0"
        target = index + offset
        if target >= len(parts):
            return "0"
        return parts[target]

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
