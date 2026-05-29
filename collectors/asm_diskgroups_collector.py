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

    def collect_host(self, cluster_name: str, host: "HostConfig", logger: logging.Logger, *, enabled: bool = True, timeout_seconds: int = 30) -> list[ASMDiskgroupRecord]:
        logger.info("Starting ASM diskgroup collection for %s", host.name)
        if not enabled:
            reason = "asm_collection_disabled"
            logger.warning("ASM diskgroup collection failed: error=%s", reason)
            return [ASMDiskgroupRecord(cluster=cluster_name, host=host.name, address=host.address, asm_collection_status="failed", warning_level="ERROR", asm_collection_error=reason, asm_error=reason)]

        script = ASM_COLLECTION_SCRIPT.replace("__ASM_TIMEOUT_SECONDS__", str(max(1, int(timeout_seconds))))
        result = self.runner.run_script(host, script)
        if not result.ok:
            reason = result.error or result.stderr.strip() or f"SSH exited with {result.returncode}"
            logger.warning("ASM diskgroup collection failed: error=%s", reason)
            return [ASMDiskgroupRecord(cluster=cluster_name, host=host.name, address=host.address, asm_collection_status="failed", warning_level="ERROR", asm_collection_error=reason, asm_error=reason, asm_stderr=result.stderr, asm_stdout=result.stdout)]

        rows = _parse_lsdg(cluster_name, host.name, host.address, _parse_sections(result.stdout))
        dg_rows = [r for r in rows if r.diskgroup_name and r.total_mb > 0]
        summary = rows[-1]
        if summary.asm_collection_status == "success" and dg_rows:
            logger.info("Completed ASM diskgroup collection: status=success rows=%s", len(dg_rows))
        elif summary.asm_collection_status == "partial" and dg_rows:
            logger.warning("ASM diskgroup collection partial: rows=%s error=%s", len(dg_rows), summary.asm_collection_error or summary.asm_error or "unknown")
        else:
            logger.warning("ASM diskgroup collection failed: error=%s", summary.asm_collection_error or summary.asm_error or "unknown")
        return rows


def _parse_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in output.splitlines():
        if line.startswith(BEGIN_PREFIX) and line.endswith("==="):
            current = line[len(BEGIN_PREFIX):-3].strip()
            sections[current] = []
            continue
        if line.startswith("__ERIC_SECTION__:"):
            current = line.split(":", 1)[1].strip()
            if current == "asm_lsdg":
                current = "asmcmd_lsdg"
            sections[current] = []
            continue
        if line.startswith(END_PREFIX) and line.endswith("==="):
            current = None
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _parse_lsdg(cluster: str, host: str, address: str, sections: dict[str, str]) -> list[ASMDiskgroupRecord]:
    env_stdout = sections.get("asm_env", "").strip()
    env = _parse_env_section(env_stdout)
    status = sections.get("asm_collection_status", "failed").strip() or "failed"
    asmcmd_stdout = sections.get("asmcmd_stdout", sections.get("asm_stdout", sections.get("asmcmd_lsdg", ""))).strip()
    asmcmd_stderr = sections.get("asmcmd_stderr", sections.get("asm_stderr", "")).strip()
    sqlplus_stdout = sections.get("sqlplus_stdout", sections.get("sqlplus_fallback", "")).strip()
    sqlplus_stderr = sections.get("sqlplus_stderr", "").strip()
    asm_rc = sections.get("asm_returncode", "").strip()
    sqlplus_rc = sections.get("sqlplus_returncode", "").strip()
    asm_error = sections.get("asm_error", "").strip()
    asm_collection_error = sections.get("asm_collection_error", "").strip() or asm_error

    rows = _parse_asmcmd_rows(cluster, host, address, asmcmd_stdout, status)
    source_had_output = bool(asmcmd_stdout.strip())
    if not rows and sqlplus_stdout:
        rows = _parse_sqlplus_rows(cluster, host, address, sqlplus_stdout, status)
        source_had_output = True

    env_missing = [name for name in ("grid_home", "grid_owner", "asm_sid") if not env.get(name)]
    if env_missing and env_stdout:
        status = "failed_env"
        if not asm_collection_error:
            asm_collection_error = "missing_" + "_".join(env_missing)
    elif rows:
        status = "success" if status == "success" else "partial"
    elif (asm_rc and asm_rc != "0") and (not sqlplus_rc or sqlplus_rc != "0"):
        status = "failed_asmcmd"
        if not asm_collection_error:
            asm_collection_error = f"asmcmd_failed_rc_{asm_rc or 'unknown'};sqlplus_failed_rc_{sqlplus_rc or 'not_run'}"
    elif source_had_output and not status.startswith("failed"):
        status = "failed_parse"
        if not asm_collection_error:
            asm_collection_error = "failed_parse_no_valid_diskgroup_rows"
    else:
        status = status if status.startswith("failed") else "failed_asmcmd"
        if not asm_collection_error:
            asm_collection_error = "no_asm_output_returned"

    if not asm_error:
        asm_error = asm_collection_error

    debug_fields = {
        "grid_home": env.get("grid_home", ""),
        "grid_owner": env.get("grid_owner", ""),
        "asm_sid": env.get("asm_sid", ""),
        "asmcmd_path": env.get("asmcmd_path", ""),
        "asm_command": sections.get("asm_command", "").strip(),
        "asm_env_stdout": env_stdout,
        "asm_stdout": asmcmd_stdout,
        "asm_stderr": asmcmd_stderr,
        "asm_returncode": asm_rc,
        "asmcmd_stdout": asmcmd_stdout,
        "asmcmd_stderr": asmcmd_stderr,
        "sqlplus_stdout": sqlplus_stdout,
        "sqlplus_stderr": sqlplus_stderr,
        "sqlplus_returncode": sqlplus_rc,
    }
    for row in rows:
        row.asm_collection_status = status
        row.asm_collection_error = asm_collection_error
        row.asm_error = asm_error
        for key, value in debug_fields.items():
            setattr(row, key, value)

    summary = ASMDiskgroupRecord(
        cluster=cluster,
        host=host,
        address=address,
        warning_level="ERROR" if status.startswith("failed") else "",
        asm_collection_status=status,
        asm_collection_error=asm_collection_error,
        asm_error=asm_error,
        **debug_fields,
    )
    if not rows or status != "success":
        rows.append(summary)
    return rows


def _parse_asmcmd_rows(cluster: str, host: str, address: str, text: str, status: str) -> list[ASMDiskgroupRecord]:
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
        diskgroup_name = parts[12].rstrip("/")
        row = _build_diskgroup_record(cluster, host, address, diskgroup_name, parts[0], parts[1], total_mb, free_mb, usable_file_mb, status)
        if row:
            rows.append(row)
    return rows


def _parse_sqlplus_rows(cluster: str, host: str, address: str, text: str, status: str) -> list[ASMDiskgroupRecord]:
    rows: list[ASMDiskgroupRecord] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped or stripped.upper().startswith(("SQL>", "SP2-", "ORA-")):
            continue
        parts = [part.strip() for part in stripped.split("|")]
        if len(parts) < 6:
            continue
        row = _build_diskgroup_record(cluster, host, address, parts[0].rstrip("/"), parts[1], parts[2], _to_int(parts[3]), _to_int(parts[4]), _to_int(parts[5]), status)
        if row:
            rows.append(row)
    return rows


def _build_diskgroup_record(cluster: str, host: str, address: str, diskgroup_name: str, state: str, dg_type: str, total_mb: int, free_mb: int, usable_file_mb: int, status: str) -> ASMDiskgroupRecord | None:
    if not diskgroup_name or total_mb <= 0:
        return None
    used_pct = round(((total_mb - free_mb) / total_mb) * 100, 2)
    warning_level = "OK"
    if used_pct >= 95:
        warning_level = "CRITICAL"
    elif used_pct >= 85:
        warning_level = "WARNING"
    return ASMDiskgroupRecord(cluster=cluster, host=host, address=address, diskgroup_name=diskgroup_name, state=state, type=dg_type, total_mb=total_mb, free_mb=free_mb, usable_file_mb=usable_file_mb, used_pct=used_pct, warning_level=warning_level, asm_collection_status=status)


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _parse_env_section(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


ASM_COLLECTION_SCRIPT = r'''
set +e
export LANG=C
export LC_ALL=C
export TERM=dumb

begin_section() { printf '===BEGIN_SECTION:%s===\n' "$1"; }
end_section() { printf '===END_SECTION:%s===\n' "$1"; }

ASM_TIMEOUT_SECONDS="${ASM_TIMEOUT_SECONDS:-__ASM_TIMEOUT_SECONDS__}"
effective_user="$(id -un 2>/dev/null || true)"
ASM_SID="$(awk -F: '/^\+ASM/ {print $1; exit}' /etc/oratab 2>/dev/null)"
GRID_HOME="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"
GRID_OWNER=""
if [ -n "$GRID_HOME" ]; then
  GRID_OWNER="$(stat -c '%U' "$GRID_HOME/bin/crsctl" 2>/dev/null || stat -c '%U' "$GRID_HOME/bin/asmcmd" 2>/dev/null || true)"
fi
asmcmd_path="$GRID_HOME/bin/asmcmd"
sqlplus_path="$GRID_HOME/bin/sqlplus"

begin_section asm_env
printf 'grid_home=%s\n' "$GRID_HOME"
printf 'grid_owner=%s\n' "$GRID_OWNER"
printf 'asm_sid=%s\n' "$ASM_SID"
printf 'asmcmd_path=%s\n' "$asmcmd_path"
printf 'effective_user=%s\n' "$effective_user"
end_section asm_env

errs=""
if [ -z "$GRID_HOME" ]; then errs="${errs} GRID_HOME_NOT_FOUND"; fi
if [ -z "$ASM_SID" ]; then errs="${errs} ASM_SID_NOT_FOUND"; fi
if [ -z "$GRID_OWNER" ]; then errs="${errs} GRID_OWNER_NOT_FOUND"; fi
if [ -n "$GRID_HOME" ] && [ ! -x "$asmcmd_path" ]; then errs="${errs} ASMCMD_NOT_FOUND"; fi

asmcmd_cmd="sudo -n -u $GRID_OWNER env ORACLE_HOME=$GRID_HOME ORACLE_SID=$ASM_SID PATH=$GRID_HOME/bin:/usr/bin:/bin $asmcmd_path lsdg"
begin_section asm_command
printf '%s\n' "$asmcmd_cmd"
end_section asm_command

if [ -n "$errs" ]; then
  begin_section asmcmd_lsdg; end_section asmcmd_lsdg
  begin_section sqlplus_fallback; end_section sqlplus_fallback
  begin_section asm_returncode; echo ""; end_section asm_returncode
  begin_section sqlplus_returncode; echo ""; end_section sqlplus_returncode
  begin_section asm_collection_status; echo failed_env; end_section asm_collection_status
  begin_section asm_collection_error; echo "${errs# }"; end_section asm_collection_error
  begin_section asm_error; echo "${errs# }"; end_section asm_error
  exit 0
fi

begin_section asmcmd_lsdg
asmcmd_combined="$(timeout "${ASM_TIMEOUT_SECONDS}s" sudo -n -u "$GRID_OWNER" env \
  ORACLE_HOME="$GRID_HOME" \
  ORACLE_SID="$ASM_SID" \
  PATH="$GRID_HOME/bin:/usr/bin:/bin" \
  "$asmcmd_path" lsdg 2>&1)"
asm_rc=$?
printf '%s\n' "$asmcmd_combined"
end_section asmcmd_lsdg
begin_section asm_returncode; echo "$asm_rc"; end_section asm_returncode
begin_section asm_stdout; printf '%s\n' "$asmcmd_combined"; end_section asm_stdout
begin_section asm_stderr
if [ "$asm_rc" -ne 0 ]; then printf '%s\n' "$asmcmd_combined"; fi
end_section asm_stderr
begin_section asmcmd_stdout; printf '%s\n' "$asmcmd_combined"; end_section asmcmd_stdout
begin_section asmcmd_stderr
if [ "$asm_rc" -ne 0 ]; then printf '%s\n' "$asmcmd_combined"; fi
end_section asmcmd_stderr

if [ "$asm_rc" -eq 0 ]; then
  begin_section sqlplus_fallback; end_section sqlplus_fallback
  begin_section sqlplus_returncode; echo ""; end_section sqlplus_returncode
  begin_section sqlplus_stdout; echo ""; end_section sqlplus_stdout
  begin_section sqlplus_stderr; echo ""; end_section sqlplus_stderr
  begin_section asm_collection_status; echo success; end_section asm_collection_status
  set -e
  exit 0
fi

begin_section sqlplus_fallback
if [ ! -x "$sqlplus_path" ]; then
  sqlplus_combined="SQLPLUS_NOT_FOUND"
  sqlplus_rc=127
else
  sqlplus_combined="$(timeout "${ASM_TIMEOUT_SECONDS}s" sudo -n -u "$GRID_OWNER" env \
    ORACLE_HOME="$GRID_HOME" \
    ORACLE_SID="$ASM_SID" \
    PATH="$GRID_HOME/bin:/usr/bin:/bin" \
    "$sqlplus_path" -s / as sysasm <<'SQL' 2>&1
set pages 0 lines 300 feedback off heading off trimspool on
select name||'|'||state||'|'||type||'|'||total_mb||'|'||free_mb||'|'||usable_file_mb
from v$asm_diskgroup;
exit
SQL
)"
  sqlplus_rc=$?
fi
printf '%s\n' "$sqlplus_combined"
end_section sqlplus_fallback
begin_section sqlplus_returncode; echo "$sqlplus_rc"; end_section sqlplus_returncode
begin_section sqlplus_stdout; printf '%s\n' "$sqlplus_combined"; end_section sqlplus_stdout
begin_section sqlplus_stderr
if [ "$sqlplus_rc" -ne 0 ]; then printf '%s\n' "$sqlplus_combined"; fi
end_section sqlplus_stderr

if [ "$sqlplus_rc" -eq 0 ]; then
  begin_section asm_collection_status; echo partial; end_section asm_collection_status
  begin_section asm_collection_error; echo "asmcmd_failed_rc_${asm_rc}"; end_section asm_collection_error
  begin_section asm_error; echo "asmcmd_failed_rc_${asm_rc}"; end_section asm_error
  set -e
  exit 0
fi

begin_section asm_collection_status; echo failed_asmcmd; end_section asm_collection_status
begin_section asm_collection_error; echo "asmcmd_failed_rc_${asm_rc};sqlplus_failed_rc_${sqlplus_rc}"; end_section asm_collection_error
begin_section asm_error; echo "asmcmd_failed_rc_${asm_rc};sqlplus_failed_rc_${sqlplus_rc}"; end_section asm_error
set -e
'''.lstrip()
