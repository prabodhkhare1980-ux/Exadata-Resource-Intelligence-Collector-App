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
    asm_stdout: str = ""
    asm_stderr: str = ""
    asm_returncode: str = ""
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
            return [ASMDiskgroupRecord(cluster=cluster_name, host=host.name, address=host.address, asm_collection_status="failed", warning_level="ERROR", asm_collection_error=reason, asm_error=reason)]

        sections = _parse_sections(result.stdout)
        rows = _parse_lsdg(cluster_name, host.name, host.address, sections)
        dg_rows = [r for r in rows if r.diskgroup_name and r.total_mb > 0]
        summary = rows[-1]
        if summary.asm_collection_status == "success" and len(dg_rows) > 0:
            logger.info("Completed ASM diskgroup collection: status=success rows=%s", len(dg_rows))
        elif summary.asm_collection_status == "partial":
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
        if line.startswith(END_PREFIX) and line.endswith("==="):
            current = None
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _parse_lsdg(cluster: str, host: str, address: str, sections: dict[str, str]) -> list[ASMDiskgroupRecord]:
    env = _parse_env_section(sections.get("asm_env", ""))
    status = sections.get("asm_collection_status", "failed").strip() or "failed"
    asm_lsdg_text = sections.get("asmcmd_lsdg", "") or sections.get("sqlplus_fallback", "")
    rows: list[ASMDiskgroupRecord] = []
    for line in asm_lsdg_text.splitlines():
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
        if not diskgroup_name or total_mb <= 0:
            continue
        used_pct = round(((total_mb - free_mb) / total_mb) * 100, 2)
        warning_level = "OK"
        if used_pct >= 95:
            warning_level = "CRITICAL"
        elif used_pct >= 85:
            warning_level = "WARNING"
        rows.append(ASMDiskgroupRecord(cluster=cluster, host=host, address=address, diskgroup_name=diskgroup_name, state=parts[0], type=parts[1], total_mb=total_mb, free_mb=free_mb, usable_file_mb=usable_file_mb, used_pct=used_pct, warning_level=warning_level, asm_collection_status=status))

    asm_error = sections.get("asm_error", "").strip()
    asm_collection_error = sections.get("asm_collection_error", "").strip() or asm_error
    if status == "success" and not rows:
        status = "failed_parse"
        if not asm_collection_error:
            asm_collection_error = "failed_parse_no_valid_diskgroup_rows"

    summary = ASMDiskgroupRecord(
        cluster=cluster,
        host=host,
        address=address,
        warning_level="ERROR" if status.startswith("failed") else "",
        asm_collection_status=status,
        asm_collection_error=asm_collection_error,
        asm_error=asm_error,
        grid_home=env.get("grid_home", ""),
        grid_owner=env.get("grid_owner", ""),
        asm_sid=env.get("asm_sid", ""),
        asmcmd_path=env.get("asmcmd_path", ""),
        asm_command=sections.get("asm_command", "").strip(),
        asm_stdout=sections.get("asm_stdout", "").strip(),
        asm_stderr=sections.get("asm_stderr", "").strip(),
        asm_returncode=sections.get("asm_returncode", "").strip(),
        sqlplus_stdout=sections.get("sqlplus_stdout", "").strip(),
        sqlplus_stderr=sections.get("sqlplus_stderr", "").strip(),
        sqlplus_returncode=sections.get("sqlplus_returncode", "").strip(),
    )
    if status.startswith("failed") and not rows:
        rows.append(summary)
    else:
        rows.append(summary)
    return rows


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
asm_sid="$(ps -ef | grep pmon | grep ASM | awk '{print $NF}' | sed 's/.*pmon_//' | head -n1)"
grid_home="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"
grid_owner=""
if [ -n "$grid_home" ] && [ -e "$grid_home/bin/crsctl" ]; then
  grid_owner="$(stat -c '%U' "$grid_home/bin/crsctl" 2>/dev/null || true)"
fi
asmcmd_path="$grid_home/bin/asmcmd"

begin_section asm_env
printf 'grid_home=%s\n' "$grid_home"
printf 'grid_owner=%s\n' "$grid_owner"
printf 'asm_sid=%s\n' "$asm_sid"
printf 'asmcmd_path=%s\n' "$asmcmd_path"
printf 'effective_user=%s\n' "$effective_user"
end_section asm_env

errs=""
if [ -z "$grid_home" ]; then errs="${errs} GRID_HOME_NOT_FOUND"; fi
if [ -z "$asm_sid" ]; then errs="${errs} ASM_SID_NOT_FOUND"; fi
if [ -z "$grid_owner" ]; then errs="${errs} GRID_OWNER_NOT_FOUND"; fi
if [ -n "$grid_home" ] && [ ! -x "$grid_home/bin/asmcmd" ]; then errs="${errs} ASMCMD_NOT_FOUND"; fi

if [ -n "$errs" ]; then
  begin_section asm_collection_status; echo failed_env; end_section asm_collection_status
  begin_section asm_collection_error; echo "${errs# }"; end_section asm_collection_error
  begin_section asm_error; echo "${errs# }"; end_section asm_error
  exit 0
fi

asmcmd_cmd="sudo -n -u $grid_owner env ORACLE_HOME=$grid_home ORACLE_SID=$asm_sid PATH=$grid_home/bin:/usr/bin:/bin asmcmd lsdg"
begin_section asm_command
printf '%s\n' "$asmcmd_cmd"
end_section asm_command

begin_section asmcmd_lsdg
asm_stdout="$(timeout "${ASM_TIMEOUT_SECONDS}s" sudo -n -u "$grid_owner" env ORACLE_HOME="$grid_home" ORACLE_SID="$asm_sid" PATH="$grid_home/bin:/usr/bin:/bin" "$grid_home/bin/asmcmd" lsdg 2>&1)"
asm_rc=$?
printf '%s\n' "$asm_stdout"
end_section asmcmd_lsdg
begin_section asm_returncode; echo "$asm_rc"; end_section asm_returncode
begin_section asm_stdout; printf '%s\n' "$asm_stdout"; end_section asm_stdout
begin_section asm_stderr; printf '%s\n' ""; end_section asm_stderr

if [ "$asm_rc" -eq 0 ]; then
  begin_section asm_collection_status; echo success; end_section asm_collection_status
  exit 0
fi

begin_section sqlplus_fallback
sqlplus_stdout="$(timeout "${ASM_TIMEOUT_SECONDS}s" sudo -n -u "$grid_owner" env ORACLE_HOME="$grid_home" ORACLE_SID="$asm_sid" PATH="$grid_home/bin:/usr/bin:/bin" "$grid_home/bin/sqlplus" -s / as sysasm <<'SQL' 2>&1
set pages 0 lines 300 feedback off heading off trimspool on
select name||'|'||state||'|'||type||'|'||total_mb||'|'||free_mb||'|'||usable_file_mb from v\$asm_diskgroup;
exit
SQL
)"
sqlplus_rc=$?
printf '%s\n' "$sqlplus_stdout"
end_section sqlplus_fallback
begin_section sqlplus_returncode; echo "$sqlplus_rc"; end_section sqlplus_returncode
begin_section sqlplus_stdout; printf '%s\n' "$sqlplus_stdout"; end_section sqlplus_stdout
begin_section sqlplus_stderr; printf '%s\n' ""; end_section sqlplus_stderr

if [ "$sqlplus_rc" -eq 0 ]; then
  begin_section asm_collection_status; echo partial; end_section asm_collection_status
  exit 0
fi

begin_section asm_collection_status; echo failed_asmcmd; end_section asm_collection_status
begin_section asm_collection_error; echo "asmcmd_failed_rc_${asm_rc};sqlplus_failed_rc_${sqlplus_rc}"; end_section asm_collection_error
begin_section asm_error; echo "asmcmd_failed_rc_${asm_rc};sqlplus_failed_rc_${sqlplus_rc}"; end_section asm_error
'''.lstrip()
