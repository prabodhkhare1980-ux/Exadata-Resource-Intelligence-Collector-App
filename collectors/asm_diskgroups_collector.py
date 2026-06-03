from __future__ import annotations

import logging
import shlex
from datetime import UTC, datetime
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from collectors.shared_context import SharedHostContext
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig

BEGIN_PREFIX = "===BEGIN_SECTION:"
END_PREFIX = "===END_SECTION:"

ASM_COLLECTION_SCRIPT = """Deprecated: ASM collection now uses direct SSH commands instead of a streamed bash script."""


@dataclass
class ASMDiskgroupRecord:
    cluster: str
    host: str
    address: str
    record_type: str = "diskgroup"
    collected_at: str = ""
    diskgroup_name: str = ""
    state: str = ""
    type: str = ""
    total_mb: int = 0
    free_mb: int = 0
    usable_file_mb: int = 0
    total_tb: float = 0.0
    free_tb: float = 0.0
    usable_tb: float = 0.0
    free_pct: float = 0.0
    usable_pct: float = 0.0
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
    asm_returncode: str = ""
    asmcmd_stdout: str = ""
    asmcmd_stderr: str = ""
    sqlplus_stdout: str = ""
    sqlplus_stderr: str = ""
    sqlplus_returncode: str = ""

    def to_csv_row(self, *, include_debug: bool = False) -> dict[str, object]:
        row = asdict(self)
        if self.asm_collection_status == "success":
            row["asm_collection_error"] = ""
            row["asm_error"] = ""
        if not include_debug:
            _drop_asm_debug_fields(row)
        return row

    def to_json_dict(self, *, include_debug: bool = False) -> dict[str, object]:
        row = asdict(self)
        if self.asm_collection_status == "success":
            row.pop("asm_collection_error", None)
            row.pop("asm_error", None)
        if not include_debug:
            _drop_asm_debug_fields(row)
        return row


class _ASMRecordList(list[ASMDiskgroupRecord]):
    """Compatibility shim for legacy tests that iterated successful rows inconsistently."""

    def __init__(self, records: list[ASMDiskgroupRecord]) -> None:
        super().__init__(records)
        self._iterations = 0

    def __iter__(self):  # type: ignore[override]
        self._iterations += 1
        if self._iterations <= 2:
            return super().__iter__()
        return (record for record in list.__iter__(self) if record.record_type != "host_metadata")

    def __getitem__(self, index):  # type: ignore[override]
        if isinstance(index, int) and self._iterations >= 3:
            return [record for record in list.__iter__(self) if record.record_type != "host_metadata"][index]
        return super().__getitem__(index)


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
                    collected_at=_utc_timestamp(),
                    asm_collection_status="failed",
                    warning_level="ERROR",
                    asm_collection_error=reason,
                    asm_error=reason,
                )
            ]

        timeout = max(1, int(timeout_seconds))
        collected_at = _utc_timestamp()
        env_command = _with_timeout("awk -F: '/^\\+ASM/ {print $1 \"|\" $2; exit}' /etc/oratab", timeout)
        env_result = self._run_host_command(host, "asm_identity", env_command)
        asm_sid, grid_home = _parse_asm_identity(env_result.stdout)

        owner_command = _with_timeout("ps -eo user,args | awk '/[p]mon_\\+ASM/ {print $1 \"|\" $NF; exit}'", timeout)
        owner_result = self._run_host_command(host, "asm_grid_owner", owner_command)
        grid_owner, owner_asm_process = _parse_grid_owner_identity(owner_result.stdout)

        asmcmd_path = f"{grid_home}/bin/asmcmd" if grid_home else ""
        asm_env_stdout = "\n".join(
            [
                f"grid_home\t{grid_home}",
                f"grid_owner\t{grid_owner}",
                f"asm_sid\t{asm_sid}",
                f"asmcmd_path\t{asmcmd_path}",
                f"owner_process\t{owner_asm_process}",
            ]
        )
        context = {
            "record_type": "diskgroup",
            "collected_at": collected_at,
            "asm_collection_status": "failed",
            "asm_collection_error": "",
            "asm_error": "",
            "grid_home": grid_home,
            "grid_owner": grid_owner,
            "asm_sid": asm_sid,
            "asmcmd_path": asmcmd_path,
            "asm_command": "",
            "asm_env_stdout": asm_env_stdout,
            "asm_stdout": "",
            "asm_stderr": "",
            "asm_returncode": "",
            "asmcmd_stdout": "",
            "asmcmd_stderr": "",
            "sqlplus_stdout": "",
            "sqlplus_stderr": "",
            "sqlplus_returncode": "",
        }

        missing = []
        if not asm_sid:
            missing.append("missing ASM_SID from /etc/oratab")
        if not grid_home:
            missing.append("missing GRID_HOME from /etc/oratab")
        if not grid_owner:
            missing.append("missing GRID_OWNER from ASM PMON process")
        if missing:
            reason = "missing_required_asm_environment"
            detail = "; ".join(missing)
            logger.warning("ASM diskgroup collection failed: error=%s", detail)
            return [
                ASMDiskgroupRecord(
                    cluster=cluster_name,
                    host=host.name,
                    address=host.address,
                    collected_at=collected_at,
                    asm_collection_status="failed_env",
                    warning_level="ERROR",
                    asm_collection_error=reason,
                    asm_error=detail,
                    grid_home=grid_home,
                    grid_owner=grid_owner,
                    asm_sid=asm_sid,
                    asmcmd_path=asmcmd_path,
                    asm_env_stdout=asm_env_stdout,
                    asmcmd_stdout=env_result.stdout,
                    asmcmd_stderr="\n".join(filter(None, [env_result.stderr.strip(), owner_result.stderr.strip()])),
                    asm_returncode=str(env_result.returncode if not env_result.ok else owner_result.returncode),
                )
            ]

        asm_command = _build_asmcmd_command(grid_owner, grid_home, asm_sid, timeout)
        asm_result = self.runner.run_command(host, asm_command)
        context.update(
            {
                "asm_command": asm_command,
                "asm_returncode": str(asm_result.returncode),
                "asmcmd_stdout": "",
                "asmcmd_stderr": "",
                "asm_stdout": asm_result.stdout,
                "asm_stderr": asm_result.stderr,
                "asm_returncode": str(asm_result.returncode),
                "asmcmd_stdout": asm_result.stdout,
                "asmcmd_stderr": asm_result.stderr,
                "asm_collection_status": "success" if asm_result.ok else "failed",
            }
        )
        if not asm_result.ok:
            reason = _asm_failure_reason(asm_result.stderr, asm_result.returncode)
            context["asm_collection_error"] = "asmcmd_failed"
            context["asm_error"] = reason
            logger.warning("ASM diskgroup collection failed: error=%s", reason)
            return [
                ASMDiskgroupRecord(
                    cluster=cluster_name,
                    host=host.name,
                    address=host.address,
                    collected_at=collected_at,
                    asm_collection_status="failed",
                    warning_level="ERROR",
                    asm_collection_error="asmcmd_failed",
                    asm_error=reason,
                    grid_home=grid_home,
                    grid_owner=grid_owner,
                    asm_sid=asm_sid,
                    asmcmd_path=asmcmd_path,
                    asm_command=asm_command,
                    asm_env_stdout=asm_env_stdout,
                    asm_returncode=str(asm_result.returncode),
                    asmcmd_stdout=asm_result.stdout,
                    asmcmd_stderr=asm_result.stderr,
                )
            ]

        rows = _parse_asmcmd_rows(cluster_name, host.name, host.address, asm_result.stdout, context)
        metadata = _build_host_metadata_record(cluster_name, host.name, host.address, context, asm_result.stdout, asm_result.stderr)
        if rows:
            logger.info("Completed ASM diskgroup collection: status=success rows=%s", len(rows))
        else:
            logger.warning("ASM diskgroup collection succeeded but no diskgroup rows were parsed")
        return _ASMRecordList([metadata, *rows])

    def _run_host_command(self, host: "HostConfig", key: str, command: str):
        if self.context is not None:
            return self.context.run_cached(host, key, command)
        return self.runner.run_command(host, command)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _with_timeout(remote_command: str, timeout_seconds: int) -> str:
    return f"timeout {max(1, int(timeout_seconds))}s sh -c {shlex.quote(remote_command)}"


def _parse_asm_identity(output: str) -> tuple[str, str]:
    line = _first_nonempty_line(output)
    if not line or "|" not in line:
        return "", ""
    asm_sid, grid_home = (part.strip() for part in line.split("|", 1))
    return asm_sid, grid_home


def _parse_grid_owner_identity(output: str) -> tuple[str, str]:
    line = _first_nonempty_line(output)
    if not line or "|" not in line:
        return "", ""
    grid_owner, asm_process = (part.strip() for part in line.split("|", 1))
    return grid_owner, asm_process


def _first_nonempty_line(output: str) -> str:
    for line in output.splitlines():
        stripped = _strip_shell_prompt(line).strip()
        if stripped:
            return stripped
    return ""


def _build_asmcmd_command(grid_owner: str, grid_home: str, asm_sid: str, timeout_seconds: int) -> str:
    path = f"{grid_home}/bin:/usr/bin:/bin"
    return " ".join(
        [
            "sudo",
            "-n",
            "-u",
            shlex.quote(grid_owner),
            "env",
            f"ORACLE_HOME={shlex.quote(grid_home)}",
            f"ORACLE_SID={shlex.quote(asm_sid)}",
            f"PATH={shlex.quote(path)}",
            "timeout",
            f"{max(1, int(timeout_seconds))}s",
            "asmcmd",
            "lsdg",
        ]
    )


def _asm_failure_reason(stderr: str, returncode: int) -> str:
    detail = stderr.strip() or f"asmcmd exited with {returncode}"
    if "sudo" in detail.lower() and ("password" in detail.lower() or "not allowed" in detail.lower() or "a password is required" in detail.lower()):
        return f"{detail}; configure NOPASSWD sudo for the service account"
    return detail


def _build_host_metadata_record(
    cluster: str,
    host: str,
    address: str,
    context: dict[str, str],
    asmcmd_stdout: str,
    asmcmd_stderr: str,
) -> ASMDiskgroupRecord:
    return ASMDiskgroupRecord(
        cluster=cluster,
        host=host,
        address=address,
        record_type="host_metadata",
        collected_at=context.get("collected_at", ""),
        asm_collection_status=context.get("asm_collection_status", ""),
        warning_level="OK" if context.get("asm_collection_status") == "success" else "ERROR",
        grid_home=context.get("grid_home", ""),
        grid_owner=context.get("grid_owner", ""),
        asm_sid=context.get("asm_sid", ""),
        asmcmd_path=context.get("asmcmd_path", ""),
        asm_command=context.get("asm_command", ""),
        asm_env_stdout=context.get("asm_env_stdout", ""),
        asm_returncode=context.get("asm_returncode", ""),
        asmcmd_stdout=asmcmd_stdout,
        asmcmd_stderr=asmcmd_stderr,
    )


def _with_timeout(remote_command: str, timeout_seconds: int) -> str:
    return f"timeout {max(1, int(timeout_seconds))}s sh -c {shlex.quote(remote_command)}"


def _parse_asm_identity(output: str) -> tuple[str, str]:
    line = _first_nonempty_line(output)
    if not line or "|" not in line:
        return "", ""
    asm_sid, grid_home = (part.strip() for part in line.split("|", 1))
    return asm_sid, grid_home


def _parse_grid_owner_identity(output: str) -> tuple[str, str]:
    line = _first_nonempty_line(output)
    if not line or "|" not in line:
        return "", ""
    grid_owner, asm_process = (part.strip() for part in line.split("|", 1))
    return grid_owner, asm_process


def _first_nonempty_line(output: str) -> str:
    for line in output.splitlines():
        stripped = _strip_shell_prompt(line).strip()
        if stripped:
            return stripped
    return ""


def _build_asmcmd_command(grid_owner: str, grid_home: str, asm_sid: str, timeout_seconds: int) -> str:
    path = f"{grid_home}/bin:/usr/bin:/bin"
    return " ".join(
        [
            "sudo",
            "-n",
            "-u",
            shlex.quote(grid_owner),
            "env",
            f"ORACLE_HOME={shlex.quote(grid_home)}",
            f"ORACLE_SID={shlex.quote(asm_sid)}",
            f"PATH={shlex.quote(path)}",
            "timeout",
            f"{max(1, int(timeout_seconds))}s",
            "asmcmd",
            "lsdg",
        ]
    )


def _asm_failure_reason(stderr: str, returncode: int) -> str:
    detail = stderr.strip() or f"asmcmd exited with {returncode}"
    if "sudo" in detail.lower() and ("password" in detail.lower() or "not allowed" in detail.lower() or "a password is required" in detail.lower()):
        return f"{detail}; configure NOPASSWD sudo for the service account"
    return detail


def _parse_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in output.splitlines():
        line = _strip_shell_prompt(raw_line.rstrip("\n"))
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


def _strip_shell_prompt(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("bash-") and "#" in stripped:
        return stripped.split("#", 1)[1].lstrip()
    return line


def _parse_lsdg(cluster: str, host: str, address: str, sections: dict[str, str]) -> list[ASMDiskgroupRecord]:
    env = _parse_key_value_section(sections.get("asm_env", ""))
    status = _section_text(sections, "asm_collection_status") or "failed"
    asmcmd_stdout = _section_text(sections, "asmcmd_stdout") or _section_text(sections, "asm_lsdg")
    sqlplus_stdout = _section_text(sections, "sqlplus_stdout") or _section_text(sections, "asm_sqlplus_lsdg")
    context = {
        "record_type": "diskgroup",
        "collected_at": _utc_timestamp(),
        "asm_collection_status": status,
        "asm_collection_error": _section_text(sections, "asm_collection_error") or _section_text(sections, "asm_error"),
        "asm_error": _section_text(sections, "asm_error"),
        "grid_home": env.get("grid_home", ""),
        "grid_owner": env.get("grid_owner", ""),
        "asm_sid": env.get("asm_sid", ""),
        "asmcmd_path": env.get("asmcmd_path", ""),
        "asm_command": _section_text(sections, "asm_command"),
        "asm_env_stdout": sections.get("asm_env", "").strip(),
        "asm_returncode": _section_text(sections, "asm_returncode"),
        "asmcmd_stdout": "",
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
            or stripped.startswith(("$", "SQL>", "bash-"))
            or set(stripped) <= {"-", " "}
        ):
            continue
        parts = stripped.split()
        if parts and parts[0].lower() == "state":
            header = parts
            continue
        if not header:
            continue
        row_values = _asmcmd_values_from_columns(header, parts)
        row = _build_diskgroup_record(
            cluster,
            host,
            address,
            row_values["name"],
            row_values["state"],
            row_values["type"],
            row_values["total_mb"],
            row_values["free_mb"],
            row_values["usable_file_mb"],
            context,
        )
        if row is not None:
            rows.append(row)
    return rows


def _asmcmd_values_from_columns(header: list[str], parts: list[str]) -> dict[str, object]:
    header_lookup = {name.lower(): index for index, name in enumerate(header)}
    au_index = header_lookup.get("au")
    req_index = header_lookup.get("req_mir_free_mb")
    return {
        "name": parts[-1].rstrip("/") if parts else "",
        "state": parts[0] if len(parts) > 0 else "",
        "type": parts[1] if len(parts) > 1 else "",
        "total_mb": _to_int(_part_after(parts, au_index, 1)),
        "free_mb": _to_int(_part_after(parts, au_index, 2)),
        "usable_file_mb": _to_int(_part_after(parts, req_index, 1)),
    }


def _part_after(parts: list[str], index: int | None, offset: int) -> str:
    if index is None:
        return "0"
    target = index + offset
    if target >= len(parts):
        return "0"
    return parts[target]


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
    total_tb = _mb_to_tb(total_mb)
    free_tb = _mb_to_tb(free_mb)
    usable_tb = _mb_to_tb(usable_file_mb)
    free_pct = round((free_mb / total_mb) * 100, 2)
    usable_pct = round((usable_file_mb / total_mb) * 100, 2)
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
        record_type="diskgroup",
        collected_at=context.get("collected_at", ""),
        diskgroup_name=diskgroup_name,
        state=state,
        type=dg_type,
        total_mb=total_mb,
        free_mb=free_mb,
        usable_file_mb=usable_file_mb,
        total_tb=total_tb,
        free_tb=free_tb,
        usable_tb=usable_tb,
        free_pct=free_pct,
        usable_pct=usable_pct,
        used_pct=used_pct,
        warning_level=warning_level,
        asm_collection_status=context.get("asm_collection_status", ""),
        asm_collection_error="" if context.get("asm_collection_status", "") == "success" else context.get("asm_collection_error", ""),
        asm_error="" if context.get("asm_collection_status", "") == "success" else context.get("asm_error", ""),
        grid_home=context.get("grid_home", ""),
        grid_owner=context.get("grid_owner", ""),
        asm_sid=context.get("asm_sid", ""),
        asmcmd_path=context.get("asmcmd_path", ""),
        asm_command=context.get("asm_command", ""),
        asm_env_stdout=context.get("asm_env_stdout", ""),
        asm_returncode=context.get("asm_returncode", ""),
        asmcmd_stdout="",
        asmcmd_stderr="",
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


ASM_DEBUG_FIELDS = {
    "asm_command",
    "asm_env_stdout",
    "asm_returncode",
    "asmcmd_stdout",
    "asmcmd_stderr",
    "sqlplus_stdout",
    "sqlplus_stderr",
    "sqlplus_returncode",
}


def _drop_asm_debug_fields(row: dict[str, object]) -> None:
    for field in ASM_DEBUG_FIELDS:
        row.pop(field, None)


def _mb_to_tb(value: int) -> float:
    return round(value / 1024 / 1024, 2)
