from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from collectors.shared_context import SharedHostContext
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig

BEGIN_PREFIX = "===BEGIN_SECTION:"
END_PREFIX = "===END_SECTION:"

ASM_COLLECTION_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail

asm_timeout="__ASM_TIMEOUT_SECONDS__"

emit_section() {
  section_name="$1"
  printf '===BEGIN_SECTION:%s===\n' "$section_name"
  cat
  printf '===END_SECTION:%s===\n' "$section_name"
}

emit_value_section() {
  section_name="$1"
  value="$2"
  printf '===BEGIN_SECTION:%s===\n' "$section_name"
  printf '%s\n' "$value"
  printf '===END_SECTION:%s===\n' "$section_name"
}

ASM_SID="$(ps -ef | awk '/[p]mon_\+ASM/ {sub(/^.*pmon_/,"",$NF); print $NF; exit}' 2>/dev/null || true)"
GRID_HOME="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null || true)"
GRID_OWNER=""

GRID_OWNER="$(ps -eo user,args 2>/dev/null | awk '/[a]sm_pmon/ {print $1; exit}' || true)"
if [ -z "$GRID_OWNER" ]; then
  GRID_OWNER="$(ps -eo user,args 2>/dev/null | awk '/[o]hasd/ {print $1; exit}' || true)"
fi

current_user="$(id -un 2>/dev/null || whoami 2>/dev/null || true)"
asmcmd_path="${GRID_HOME}/bin/asmcmd"
{
  printf 'grid_home\t%s\n' "$GRID_HOME"
  printf 'grid_owner\t%s\n' "$GRID_OWNER"
  printf 'asm_sid\t%s\n' "$ASM_SID"
  printf 'asmcmd_path\t%s\n' "$asmcmd_path"
  printf 'current_user\t%s\n' "$current_user"
} | emit_section asm_env

asm_error=""
asm_status="failed"
asm_collection_error=""
asm_command=""
asmcmd_rc=""
sqlplus_rc=""
asmcmd_stdout_file="$(mktemp)"
asmcmd_stderr_file="$(mktemp)"
sqlplus_stdout_file="$(mktemp)"
sqlplus_stderr_file="$(mktemp)"
cleanup() {
  rm -f "$asmcmd_stdout_file" "$asmcmd_stderr_file" "$sqlplus_stdout_file" "$sqlplus_stderr_file"
}
trap cleanup EXIT

run_as_grid() {
  if [ "$current_user" = "$GRID_OWNER" ]; then
    env ORACLE_HOME="$GRID_HOME" ORACLE_SID="$ASM_SID" PATH="$GRID_HOME/bin:/usr/bin:/bin" "$@"
  else
    sudo -n -u "$GRID_OWNER" env ORACLE_HOME="$GRID_HOME" ORACLE_SID="$ASM_SID" PATH="$GRID_HOME/bin:/usr/bin:/bin" "$@"
  fi
}

if [ -z "$ASM_SID" ] || [ -z "$GRID_HOME" ] || [ -z "$GRID_OWNER" ]; then
  asm_status="failed_env"
  asm_collection_error="missing_required_asm_environment"
  if [ -z "$ASM_SID" ]; then asm_error="missing ASM_SID from PMON"; fi
  if [ -z "$GRID_HOME" ]; then asm_error="${asm_error}${asm_error:+; }missing GRID_HOME from /etc/oratab"; fi
  if [ -z "$GRID_OWNER" ]; then asm_error="${asm_error}${asm_error:+; }missing GRID_OWNER from ASM PMON/OHASD processes"; fi
else
  if [ "$current_user" = "$GRID_OWNER" ]; then
    asm_command="env ORACLE_HOME=\"$GRID_HOME\" ORACLE_SID=\"$ASM_SID\" PATH=\"$GRID_HOME/bin:/usr/bin:/bin\" timeout ${asm_timeout}s asmcmd lsdg"
  else
    asm_command="sudo -n -u \"$GRID_OWNER\" env ORACLE_HOME=\"$GRID_HOME\" ORACLE_SID=\"$ASM_SID\" PATH=\"$GRID_HOME/bin:/usr/bin:/bin\" timeout ${asm_timeout}s asmcmd lsdg"
  fi

  set +e
  run_as_grid timeout "${asm_timeout}s" asmcmd lsdg >"$asmcmd_stdout_file" 2>"$asmcmd_stderr_file"
  asm_rc=$?
  asmcmd_rc="$asm_rc"
  set -e

  if [ "$asmcmd_rc" -eq 0 ]; then
    asm_status="success"
  else
    asm_collection_error="asmcmd_failed"
    set +e
    run_as_grid timeout "${asm_timeout}s" sqlplus -s / as sysasm >"$sqlplus_stdout_file" 2>"$sqlplus_stderr_file" <<'SQL'
set pages 0 lines 32767 feedback off verify off heading off echo off trimspool on
select name||'|'||state||'|'||type||'|'||total_mb||'|'||free_mb||'|'||usable_file_mb from v$asm_diskgroup;
exit
SQL
    sqlplus_rc=$?
    set -e
    if [ "$sqlplus_rc" -eq 0 ]; then
      asm_status="success"
      asm_collection_error="asmcmd_failed_sqlplus_succeeded"
    else
      asm_status="failed"
      asm_collection_error="asmcmd_and_sqlplus_failed"
      asm_error="asmcmd rc=${asmcmd_rc}; sqlplus rc=${sqlplus_rc}; NOPASSWD sudo may be required when SSH user differs from GRID_OWNER"
    fi
  fi
fi

emit_value_section asm_command "$asm_command"
emit_section asmcmd_stdout <"$asmcmd_stdout_file"
emit_section asmcmd_stderr <"$asmcmd_stderr_file"
emit_value_section asm_returncode "$asmcmd_rc"
emit_section sqlplus_stdout <"$sqlplus_stdout_file"
emit_section sqlplus_stderr <"$sqlplus_stderr_file"
emit_value_section sqlplus_returncode "$sqlplus_rc"
emit_value_section asm_collection_status "$asm_status"
emit_value_section asm_collection_error "$asm_collection_error"
emit_value_section asm_error "$asm_error"
'''


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
    asm_collection_error: str = ""
    asm_error: str = ""
    grid_home: str = ""
    grid_owner: str = ""
    asm_sid: str = ""
    asmcmd_path: str = ""
    asm_command: str = ""
    asm_env_stdout: str = ""
    asm_stdout: str = ""
    asm_stderr: str = ""
    asm_returncode: str = ""
    asmcmd_stdout: str = ""
    asmcmd_stderr: str = ""
    sqlplus_stdout: str = ""
    sqlplus_stderr: str = ""
    sqlplus_returncode: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return asdict(self)

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


class ASMDiskgroupCollector:
    def __init__(self, runner: SSHRunner, context: SharedHostContext | None = None, logger: logging.Logger | None = None) -> None:
        self.runner = runner
        self.context = context
        self.logger = logger or logging.getLogger(__name__)

    def collect_host(
        self,
        cluster_name: str,
        host: "HostConfig",
        logger: logging.Logger,
        *,
        enabled: bool = True,
        timeout_seconds: int = 30,
    ) -> list[ASMDiskgroupRecord]:
        logger.info("Starting ASM diskgroup collection for %s", host.name)
        if not enabled:
            reason = "asm_collection_disabled"
            logger.warning("ASM diskgroup collection skipped: error=%s", reason)
            return [
                ASMDiskgroupRecord(
                    cluster=cluster_name,
                    host=host.name,
                    address=host.address,
                    asm_collection_status="failed",
                    warning_level="ERROR",
                    asm_collection_error=reason,
                    asm_error=reason,
                )
            ]

        script = ASM_COLLECTION_SCRIPT.replace("__ASM_TIMEOUT_SECONDS__", str(max(1, int(timeout_seconds))))
        result = self.runner.run_script(host, script)
        if not result.ok:
            reason = result.error or result.stderr.strip() or f"SSH exited with {result.returncode}"
            logger.warning("ASM diskgroup collection failed: error=%s", reason)
            return [
                ASMDiskgroupRecord(
                    cluster=cluster_name,
                    host=host.name,
                    address=host.address,
                    asm_collection_status="failed",
                    warning_level="ERROR",
                    asm_collection_error=reason,
                    asm_error=reason,
                    asm_stderr=result.stderr,
                    asm_stdout=result.stdout,
                )
            ]

        sections = _parse_sections(result.stdout)
        rows = _parse_lsdg(cluster_name, host.name, host.address, sections)
        status = _section_text(sections, "asm_collection_status") or "failed"
        if status == "success" and rows:
            logger.info("Completed ASM diskgroup collection: status=success rows=%s", len(rows))
        elif status == "success":
            logger.warning("ASM diskgroup collection succeeded but no diskgroup rows were parsed")
        else:
            error = _section_text(sections, "asm_collection_error") or _section_text(sections, "asm_error") or "unknown"
            logger.warning("ASM diskgroup collection failed: error=%s", error)
        return rows


def _parse_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith(BEGIN_PREFIX) and line.endswith("==="):
            current = line[len(BEGIN_PREFIX) : -3]
            sections.setdefault(current, [])
            continue
        if line.startswith(END_PREFIX) and line.endswith("==="):
            current = None
            continue
        # Backward-compatible parsing for old fixtures; new scripts emit only BEGIN/END sections.
        if line.startswith("__ERIC_SECTION__:"):
            current = line.split(":", 1)[1]
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines).strip("\n") for name, lines in sections.items()}


def _parse_lsdg(cluster: str, host: str, address: str, sections: dict[str, str]) -> list[ASMDiskgroupRecord]:
    env = _parse_key_value_section(sections.get("asm_env", ""))
    status = _section_text(sections, "asm_collection_status") or "failed"
    asmcmd_stdout = _section_text(sections, "asmcmd_stdout") or _section_text(sections, "asm_lsdg")
    sqlplus_stdout = _section_text(sections, "sqlplus_stdout") or _section_text(sections, "asm_sqlplus_lsdg")
    context = {
        "asm_collection_status": status,
        "asm_collection_error": _section_text(sections, "asm_collection_error") or _section_text(sections, "asm_error"),
        "asm_error": _section_text(sections, "asm_error"),
        "grid_home": env.get("grid_home", ""),
        "grid_owner": env.get("grid_owner", ""),
        "asm_sid": env.get("asm_sid", ""),
        "asmcmd_path": env.get("asmcmd_path", ""),
        "asm_command": _section_text(sections, "asm_command"),
        "asm_env_stdout": sections.get("asm_env", "").strip(),
        "asm_stdout": asmcmd_stdout,
        "asm_stderr": _section_text(sections, "asmcmd_stderr"),
        "asm_returncode": _section_text(sections, "asm_returncode"),
        "asmcmd_stdout": asmcmd_stdout,
        "asmcmd_stderr": _section_text(sections, "asmcmd_stderr"),
        "sqlplus_stdout": sqlplus_stdout,
        "sqlplus_stderr": _section_text(sections, "sqlplus_stderr"),
        "sqlplus_returncode": _section_text(sections, "sqlplus_returncode"),
    }

    rows = _parse_asmcmd_rows(cluster, host, address, asmcmd_stdout, context)
    if not rows:
        rows = _parse_sqlplus_rows(cluster, host, address, sqlplus_stdout, context)
    return rows


def _parse_asmcmd_rows(cluster: str, host: str, address: str, output: str, context: dict[str, str]) -> list[ASMDiskgroupRecord]:
    rows: list[ASMDiskgroupRecord] = []
    header: list[str] | None = None
    for line in output.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if (
            not stripped
            or lower.startswith(("asm", "ora-", "sp2-"))
            or stripped.startswith(("$", "SQL>"))
            or set(stripped) <= {"-", " "}
        ):
            continue
        parts = stripped.split()
        if parts and parts[0].lower() == "state":
            header = parts
            continue
        if not header:
            continue
        values = dict(zip(header, parts))
        row = _build_diskgroup_record(
            cluster,
            host,
            address,
            values.get("Name", "").rstrip("/"),
            values.get("State", ""),
            values.get("Type", ""),
            _to_int(values.get("Total_MB", "0")),
            _to_int(values.get("Free_MB", "0")),
            _to_int(values.get("Usable_file_MB", "0")),
            context,
        )
        if row is not None:
            rows.append(row)
    return rows


def _parse_sqlplus_rows(cluster: str, host: str, address: str, output: str, context: dict[str, str]) -> list[ASMDiskgroupRecord]:
    rows: list[ASMDiskgroupRecord] = []
    for line in output.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if not stripped or "|" not in stripped or upper.startswith(("SQL>", "SP2-", "ORA-")):
            continue
        parts = [part.strip() for part in stripped.split("|")]
        if len(parts) < 6:
            continue
        row = _build_diskgroup_record(
            cluster,
            host,
            address,
            parts[0].rstrip("/"),
            parts[1],
            parts[2],
            _to_int(parts[3]),
            _to_int(parts[4]),
            _to_int(parts[5]),
            context,
        )
        if row is not None:
            rows.append(row)
    return rows


def _build_diskgroup_record(
    cluster: str,
    host: str,
    address: str,
    diskgroup_name: str,
    state: str,
    dg_type: str,
    total_mb: int,
    free_mb: int,
    usable_file_mb: int,
    context: dict[str, str],
) -> ASMDiskgroupRecord | None:
    if not diskgroup_name or total_mb <= 0:
        return None
    used_pct = round(((total_mb - free_mb) / total_mb) * 100, 2)
    warning_level = "OK"
    if used_pct >= 95:
        warning_level = "CRITICAL"
    elif used_pct >= 85:
        warning_level = "WARNING"
    return ASMDiskgroupRecord(
        cluster=cluster,
        host=host,
        address=address,
        diskgroup_name=diskgroup_name,
        state=state,
        type=dg_type,
        total_mb=total_mb,
        free_mb=free_mb,
        usable_file_mb=usable_file_mb,
        used_pct=used_pct,
        warning_level=warning_level,
        asm_collection_status=context.get("asm_collection_status", ""),
        asm_collection_error=context.get("asm_collection_error", ""),
        asm_error=context.get("asm_error", ""),
        grid_home=context.get("grid_home", ""),
        grid_owner=context.get("grid_owner", ""),
        asm_sid=context.get("asm_sid", ""),
        asmcmd_path=context.get("asmcmd_path", ""),
        asm_command=context.get("asm_command", ""),
        asm_env_stdout=context.get("asm_env_stdout", ""),
        asm_stdout=context.get("asm_stdout", ""),
        asm_stderr=context.get("asm_stderr", ""),
        asm_returncode=context.get("asm_returncode", ""),
        asmcmd_stdout=context.get("asmcmd_stdout", ""),
        asmcmd_stderr=context.get("asmcmd_stderr", ""),
        sqlplus_stdout=context.get("sqlplus_stdout", ""),
        sqlplus_stderr=context.get("sqlplus_stderr", ""),
        sqlplus_returncode=context.get("sqlplus_returncode", ""),
    )

def _parse_key_value_section(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "\t" not in line:
            continue
        key, value = line.split("\t", 1)
        values[key.strip()] = value.strip()
    return values


def _section_text(sections: dict[str, str], name: str) -> str:
    return sections.get(name, "").strip()


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
