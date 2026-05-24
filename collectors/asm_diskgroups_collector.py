"""ASM diskgroup collector."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from collectors.shared_context import SharedHostContext
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig

SECTION_PREFIX = "__ERIC_SECTION__:"


@dataclass
class ASMDiskgroupRecord:
    cluster: str
    host: str
    address: str
    diskgroup_name: str = ""
    state: str = ""
    type: str = ""
    total_mb: int = 0
    free_mb: int = 0
    usable_file_mb: int = 0
    used_pct: float = 0.0
    warning_level: str = ""
    asm_collection_status: str = ""
    asm_error: str = ""
    asm_stderr: str = ""
    asm_stdout: str = ""
    asm_command: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return asdict(self)

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


class ASMDiskgroupCollector:
    def __init__(self, runner: SSHRunner, context: SharedHostContext | None = None, logger: logging.Logger | None = None) -> None:
        self.runner = runner
        self.context = context
        self.logger = logger or logging.getLogger(__name__)

    def collect_host(self, cluster_name: str, host: "HostConfig", logger: logging.Logger, *, enabled: bool = True, timeout_seconds: int = 30) -> list[ASMDiskgroupRecord]:
        logger.info("Starting ASM diskgroup collection for %s", host.name)
        if not enabled:
            reason = "asm_collection_disabled"
            logger.warning("ASM collection failed for %s: %s", host.name, reason)
            return [ASMDiskgroupRecord(cluster=cluster_name, host=host.name, address=host.address, asm_collection_status="failed", asm_error=reason)]

        script = ASM_COLLECTION_SCRIPT.replace("__ASM_TIMEOUT_SECONDS__", str(max(1, int(timeout_seconds))))
        result = self.runner.run_script(host, script)
        if not result.ok:
            reason = result.error or result.stderr.strip() or f"SSH exited with {result.returncode}"
            logger.warning("ASM collection failed for %s: %s", host.name, reason)
            return [ASMDiskgroupRecord(cluster=cluster_name, host=host.name, address=host.address, asm_collection_status="failed", warning_level="ERROR", asm_error=reason)]

        sections = _parse_sections(result.stdout)
        status = sections.get("asm_collection_status", "failed").strip() or "failed"
        rows = _parse_lsdg(cluster_name, host.name, host.address, sections.get("asm_lsdg", ""), status, sections)
        if status == "success":
            logger.info("Completed ASM diskgroup collection for %s", host.name)
        else:
            error_detail = sections.get("asm_error", "").strip() or sections.get("asm_stderr", "").strip() or sections.get("asm_stdout", "").strip()
            if error_detail:
                logger.warning("ASM collection failed for %s: %s", host.name, error_detail.splitlines()[0])
            else:
                logger.warning("ASM collection failed for %s: unknown_reason", host.name)
        return rows


def _parse_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in output.splitlines():
        if line.startswith(SECTION_PREFIX):
            current = line.removeprefix(SECTION_PREFIX).strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _parse_lsdg(cluster: str, host: str, address: str, text: str, status: str, sections: dict[str, str]) -> list[ASMDiskgroupRecord]:
    rows: list[ASMDiskgroupRecord] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("state") or set(stripped) <= {"-", " "}:
            continue
        parts = stripped.split()
        if len(parts) < 13:
            continue
        total_mb = _to_int(parts[6])
        free_mb = _to_int(parts[7])
        usable_file_mb = _to_int(parts[9])
        used_pct = round(((total_mb - free_mb) / total_mb) * 100, 2) if total_mb > 0 else 0.0
        warning_level = "OK"
        if used_pct >= 95:
            warning_level = "CRITICAL"
        elif used_pct >= 85:
            warning_level = "WARNING"
        rows.append(ASMDiskgroupRecord(cluster=cluster, host=host, address=address, diskgroup_name=parts[12].rstrip('/'), state=parts[0], type=parts[1], total_mb=total_mb, free_mb=free_mb, usable_file_mb=usable_file_mb, used_pct=used_pct, warning_level=warning_level, asm_collection_status=status))
    rows.append(
        ASMDiskgroupRecord(
            cluster=cluster,
            host=host,
            address=address,
            asm_collection_status=status,
            asm_error=sections.get("asm_error", "").strip(),
            asm_stderr=sections.get("asm_stderr", "").strip(),
            asm_stdout=sections.get("asm_stdout", "").strip(),
            asm_command=sections.get("asm_command", "").strip(),
        )
    )
    return rows


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


ASM_COLLECTION_SCRIPT = r'''
set -o pipefail
emit_section() {
  printf '\n__ERIC_SECTION__:%s\n' "$1"
}

ASM_TIMEOUT_SECONDS="${ASM_TIMEOUT_SECONDS:-__ASM_TIMEOUT_SECONDS__}"
effective_user="$(id -un 2>/dev/null || true)"
asm_sid="$(ps -ef | grep pmon | grep ASM | awk '{print $NF}' | sed 's/.*pmon_//' | head -n1)"
grid_home="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"
grid_owner=""
if [ -n "$grid_home" ] && [ -e "$grid_home/bin/crsctl" ]; then
  grid_owner="$(stat -c '%U' "$grid_home/bin/crsctl" 2>/dev/null || true)"
fi

emit_section asm_env
printf 'grid_owner\t%s\n' "${grid_owner}"
printf 'grid_home\t%s\n' "${grid_home}"
printf 'asm_sid\t%s\n' "${asm_sid}"
printf 'effective_user\t%s\n' "${effective_user}"

emit_section asm_status
if [ -z "$grid_home" ]; then echo "asm_error\tgrid_home_not_detected_from_oratab"; fi
if [ -z "$asm_sid" ]; then echo "asm_error\tasm_sid_not_detected_from_pmon"; fi
if [ -z "$grid_owner" ]; then echo "asm_error\tgrid_owner_not_detected_from_crsctl_owner"; fi
if [ -n "$grid_home" ] && [ ! -x "$grid_home/bin/asmcmd" ]; then echo "asm_error\tasmcmd_not_executable"; fi
if [ -n "$grid_home" ] && [ ! -x "$grid_home/bin/sqlplus" ]; then echo "asm_error\tsqlplus_not_executable"; fi

if [ -z "$grid_home" ] || [ -z "$asm_sid" ] || [ -z "$grid_owner" ] || [ ! -x "$grid_home/bin/asmcmd" ] || [ ! -x "$grid_home/bin/sqlplus" ]; then
  emit_section asm_collection_status
  echo failed
  emit_section asm_error
  echo "missing_required_asm_environment"
  exit 0
fi

asmcmd_cmd="sudo -n -u $grid_owner bash --noprofile --norc -c 'export ORACLE_HOME=$grid_home; export ORACLE_SID=$asm_sid; export PATH=$grid_home/bin:/usr/bin:/bin; asmcmd lsdg'"
emit_section asm_command
printf '%s\n' "$asmcmd_cmd"
emit_section asm_raw_command_test
printf "sudo -u %s env ORACLE_HOME=%s ORACLE_SID=%s PATH=%s/bin:/usr/bin:/bin asmcmd lsdg\n" "$grid_owner" "$grid_home" "$asm_sid" "$grid_home"
set +e
asm_stdout="$(timeout "${ASM_TIMEOUT_SECONDS}s" sudo -n -u "$grid_owner" bash --noprofile --norc -c "export ORACLE_HOME='$grid_home'; export ORACLE_SID='$asm_sid'; export PATH='$grid_home/bin:/usr/bin:/bin'; asmcmd lsdg" 2>/tmp/asm_stderr.$$)"
asm_rc=$?
asm_stderr="$(cat /tmp/asm_stderr.$$ 2>/dev/null || true)"
rm -f /tmp/asm_stderr.$$ >/dev/null 2>&1 || true
set -e

emit_section asm_stdout
printf '%s\n' "$asm_stdout"
emit_section asm_stderr
printf '%s\n' "$asm_stderr"
emit_section asm_lsdg
printf '%s\n' "$asm_stdout"

if [ $asm_rc -ne 0 ]; then
  sql_cmd="sudo -n -u $grid_owner bash --noprofile --norc -c 'export ORACLE_HOME=$grid_home; export ORACLE_SID=$asm_sid; export PATH=$grid_home/bin:/usr/bin:/bin; sqlplus -s / as sysasm <<\"SQL\"\nset pages 0 lines 200 feedback off verify off heading off echo off\nselect state||\" \"||type||\" N 512 4096 4194304 \"||total_mb||\" \"||free_mb||\" 0 \"||usable_file_mb||\" 0 N \"||name||\"/\" from v$asm_diskgroup;\nexit\nSQL'"
  emit_section asm_command
  printf '%s\n' "$sql_cmd"
  set +e
  sql_out="$(timeout "${ASM_TIMEOUT_SECONDS}s" sudo -n -u "$grid_owner" bash --noprofile --norc <<SQL 2>/tmp/asm_sql_stderr.$$
export ORACLE_HOME='$grid_home'
export ORACLE_SID='$asm_sid'
export PATH='$grid_home/bin:/usr/bin:/bin'
sqlplus -s / as sysasm <<'EOSQL'
set pages 0 lines 200 feedback off verify off heading off echo off
select state||' '||type||' N 512 4096 4194304 '||total_mb||' '||free_mb||' 0 '||usable_file_mb||' 0 N '||name||'/' from v\$asm_diskgroup;
exit
EOSQL
SQL
)"
  sql_rc=$?
  sql_stderr="$(cat /tmp/asm_sql_stderr.$$ 2>/dev/null || true)"
  rm -f /tmp/asm_sql_stderr.$$ >/dev/null 2>&1 || true
  set -e
  emit_section asm_stdout
  printf '%s\n' "$sql_out"
  emit_section asm_stderr
  printf '%s\n' "$sql_stderr"
  if [ $sql_rc -eq 0 ]; then
    emit_section asm_lsdg
    printf '%s\n' "$sql_out"
    emit_section asm_collection_status
    echo partial
  else
    emit_section asm_error
    echo "asmcmd_failed_rc_${asm_rc};sqlplus_failed_rc_${sql_rc}"
    emit_section asm_collection_status
    echo failed
  fi
else
  emit_section asm_collection_status
  echo success
fi
'''.lstrip()
