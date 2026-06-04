"""Oracle RAC / DB inventory collector."""

from __future__ import annotations

import json
import logging
import re
import shlex
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ssh_runner import SSHRunner
from collectors.shared_context import SharedHostContext

if TYPE_CHECKING:
    from inventory import ClusterConfig, HostConfig

SECTION_PREFIX = "__ERIC_SECTION__:"


@dataclass
class DBInventoryRecord:
    cluster: str
    host: str
    address: str
    collected_at: str
    status: str
    error: str = ""
    ssh_returncode: int | None = None
    hostname: str = ""
    date: str = ""
    gi_version: str = ""
    oratab: str = ""
    pmon_processes: list[str] = field(default_factory=list)
    databases: list[str] = field(default_factory=list)
    srvctl_config: dict[str, str] = field(default_factory=dict)
    srvctl_status: dict[str, str] = field(default_factory=dict)
    crsctl_stat_res_t: str = ""
    oracle_home_candidates: list[str] = field(default_factory=list)
    db_resource_details: list[dict[str, object]] = field(default_factory=list)
    grid_home: str = ""
    grid_owner: str = ""
    srvctl_database_list_returncode: int | None = None
    srvctl_database_list_stderr: str = ""
    db_resource_details_count: int = 0
    collection_status: str = ""
    collection_error: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    def to_csv_row(self) -> dict[str, str]:
        return {
            "cluster": self.cluster,
            "host": self.host,
            "address": self.address,
            "collected_at": self.collected_at,
            "status": self.status,
            "error": self.error,
            "ssh_returncode": "" if self.ssh_returncode is None else str(self.ssh_returncode),
            "hostname": self.hostname,
            "date": self.date,
            "gi_version": self.gi_version,
            "oratab": self.oratab,
            "pmon_processes_json": json.dumps(self.pmon_processes),
            "databases_json": json.dumps(self.databases),
            "srvctl_config_json": json.dumps(self.srvctl_config),
            "srvctl_status_json": json.dumps(self.srvctl_status),
            "crsctl_stat_res_t": self.crsctl_stat_res_t,
            "oracle_home_candidates_json": json.dumps(self.oracle_home_candidates),
            "db_resource_details_json": json.dumps(self.db_resource_details),
            "grid_home": self.grid_home,
            "grid_owner": self.grid_owner,
            "srvctl_database_list_returncode": "" if self.srvctl_database_list_returncode is None else str(self.srvctl_database_list_returncode),
            "srvctl_database_list_stderr": self.srvctl_database_list_stderr,
            "db_resource_details_count": str(self.db_resource_details_count),
            "collection_status": self.collection_status,
            "collection_error": self.collection_error,
        }

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


class DBInventoryCollector:
    def __init__(self, runner: SSHRunner, context: SharedHostContext | None = None, logger: logging.Logger | None = None) -> None:
        self.runner = runner
        self.context = context
        self.logger = logger or logging.getLogger(__name__)

    def collect_cluster(self, cluster: "ClusterConfig", host_loggers: dict[str, logging.Logger] | None = None) -> list[DBInventoryRecord]:
        records: list[DBInventoryRecord] = []
        for host in cluster.hosts:
            logger = (host_loggers or {}).get(host.name, self.logger)
            try:
                records.append(self.collect_host(cluster.name, host, logger))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unhandled DB inventory failure for %s", host.name)
                records.append(DBInventoryRecord(cluster=cluster.name, host=host.name, address=host.address, collected_at=_utc_now(), status="failed", error=str(exc)))
        return records

    def collect_host(self, cluster_name: str, host: "HostConfig", logger: logging.Logger) -> DBInventoryRecord:
        logger.info("Starting DB inventory collection for %s (%s)", host.name, host.address)
        collected_at = _utc_now()

        if self.context is None:
            result = self.runner.run_script(host, DB_INVENTORY_SCRIPT)
            if not result.ok:
                error = result.error or result.stderr.strip() or f"SSH exited with {result.returncode}"
                logger.error("DB inventory collection failed for %s: %s", host.name, error)
                return DBInventoryRecord(cluster=cluster_name, host=host.name, address=host.address, collected_at=collected_at, status="failed", error=error, ssh_returncode=result.returncode, raw={"stdout": result.stdout, "stderr": result.stderr})
            sections = _parse_sections(result.stdout)
        else:
            sections = _collect_with_context(self.context, host)
            sections["srvctl_config"] = ""
            result = self.context.run_cached(host, "db_inventory_script_status", "true")

        databases = _parse_database_list(sections.get("database_list", ""))
        pmon_sids = _parse_pmon_sids(sections.get("pmon", ""))
        srvctl_list_rc = _parse_optional_int(sections.get("srvctl_database_list_returncode", ""))
        srvctl_list_stderr = sections.get("srvctl_database_list_stderr", "").strip()
        grid_home = sections.get("grid_home", "").strip()
        grid_owner = sections.get("grid_owner", "").strip()
        logger.info("DB inventory resolved GI env: host=%s grid_home=%s grid_owner=%s", host.name, grid_home, grid_owner)
        logger.info("DB inventory database list count=%s", len(databases))
        logger.debug("Authoritative srvctl DB list: %s", databases)
        logger.debug("PMON SID list: %s", pmon_sids)
        logger.debug("srvctl loop source=srvctl_config_database")
        srvctl_config = {db: sections.get(f"srvctl_config_{db}", "") for db in databases}
        srvctl_status = {db: sections.get(f"srvctl_status_{db}", "") for db in databases}

        oracle_home_candidates = [line.strip() for line in sections.get("oracle_home_candidates", "").splitlines() if line.strip()]
        if srvctl_list_rc not in (None, 0):
            db_resource_details = _collect_pmon_oratab_fallback_details(
                self.runner,
                host,
                cluster_name,
                host.name,
                host.address,
                collected_at,
                pmon_sids,
                sections.get("oratab", ""),
                sections.get("hostname", ""),
                logger,
            )
        else:
            db_resource_details = _collect_db_resource_details(
                self.runner,
                host,
                cluster_name,
                host.name,
                host.address,
                collected_at,
                databases,
                srvctl_config,
                srvctl_status,
                oracle_home_candidates,
                sections.get("hostname", ""),
                logger,
            )
        logger.info("DB resource details rows=%s", len(db_resource_details))
        status_counts = {"success": 0, "skipped": 0, "failed": 0}
        for detail in db_resource_details:
            status_counts[str(detail.get("collection_status") or "")] = status_counts.get(str(detail.get("collection_status") or ""), 0) + 1
        logger.info(
            "DB resource details summary for %s: success=%s skipped=%s failed=%s",
            host.name,
            status_counts.get("success", 0),
            status_counts.get("skipped", 0),
            status_counts.get("failed", 0),
        )

        collection_status = "success"
        collection_error = ""
        if not databases:
            collection_status = "partial"
            collection_error = "srvctl database list empty"
        elif srvctl_list_rc not in (None, 0):
            collection_status = "partial"
            collection_error = "srvctl config database failed"

        record = DBInventoryRecord(
            cluster=cluster_name,
            host=host.name,
            address=host.address,
            collected_at=collected_at,
            status="ok" if collection_status == "success" else "partial",
            error=collection_error if collection_status != "success" else "",
            ssh_returncode=result.returncode,
            hostname=sections.get("hostname", "").strip().splitlines()[0:1][0] if sections.get("hostname", "").strip() else "",
            date=sections.get("date", "").strip(),
            gi_version=sections.get("gi_version", "").strip(),
            oratab=sections.get("oratab", "").strip(),
            pmon_processes=pmon_sids,
            databases=databases,
            srvctl_config=srvctl_config,
            srvctl_status=srvctl_status,
            crsctl_stat_res_t=sections.get("crsctl_stat_res_t", "").strip(),
            oracle_home_candidates=oracle_home_candidates,
            db_resource_details=db_resource_details,
            grid_home=grid_home,
            grid_owner=grid_owner,
            srvctl_database_list_returncode=srvctl_list_rc,
            srvctl_database_list_stderr=srvctl_list_stderr,
            db_resource_details_count=len(db_resource_details),
            collection_status=collection_status,
            collection_error=collection_error,
            raw=sections,
        )
        logger.info("Completed DB inventory collection for %s", host.name)
        return record


DB_INVENTORY_SCRIPT = r'''
set -o pipefail
emit_section() {
  printf '\n__ERIC_SECTION__:%s\n' "$1"
}

grid_oratab="$(awk -F: '/^\+ASM/ {print $1 "|" $2; exit}' /etc/oratab 2>/dev/null || true)"
grid_home=""
grid_owner=""
if [[ "$grid_oratab" == *"|"* ]]; then
  grid_home="${grid_oratab#*|}"
fi
if [ -n "$grid_home" ]; then
  grid_owner="$(stat -c '%U' "$grid_home/bin/crsctl" 2>/dev/null || true)"
fi

run_gi() {
  sudo -n -u "$grid_owner" env ORACLE_HOME="$grid_home" PATH="$grid_home/bin:/usr/bin:/bin" "$@"
}

emit_section grid_home
printf '%s\n' "$grid_home"

emit_section grid_owner
printf '%s\n' "$grid_owner"

emit_section hostname
(hostname -f 2>/dev/null || hostname 2>/dev/null) || true

emit_section date
date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true

emit_section oratab
(cat /etc/oratab 2>/dev/null || true)

emit_section pmon
(ps -ef 2>/dev/null | grep -E '[o]ra_pmon_' || true)

if [ -n "$grid_home" ] && [ -n "$grid_owner" ]; then
  stdout_file="$(mktemp)"
  stderr_file="$(mktemp)"
  set +e
  run_gi srvctl config database >"$stdout_file" 2>"$stderr_file"
  srvctl_rc=$?
  set -e
  database_list_text="$(cat "$stdout_file" 2>/dev/null || true)"
  srvctl_stderr_text="$(cat "$stderr_file" 2>/dev/null || true)"
  rm -f "$stdout_file" "$stderr_file"
else
  srvctl_rc=1
  database_list_text=""
  srvctl_stderr_text="missing GRID_HOME or GRID_OWNER"
fi

emit_section srvctl_database_list_returncode
printf '%s\n' "$srvctl_rc"

emit_section srvctl_database_list_stderr
printf '%s\n' "$srvctl_stderr_text"

emit_section database_list
printf '%s\n' "$database_list_text" | awk '{print $1}' | sed '/^$/d' | sort -u || true

emit_section gi_version
if [ -n "$grid_home" ] && [ -n "$grid_owner" ]; then
  (run_gi crsctl query crs activeversion 2>&1 || true)
fi

emit_section crsctl_stat_res_t
if [ -n "$grid_home" ] && [ -n "$grid_owner" ]; then
  (run_gi crsctl stat res -t 2>&1 || true)
fi

for db in $(printf '%s\n' "$database_list_text" | awk '{print $1}' | sed '/^$/d' | sort -u); do
  emit_section "srvctl_config_${db}"
  (run_gi srvctl config database -d "$db" 2>&1 || true)
  emit_section "srvctl_status_${db}"
  (run_gi srvctl status database -d "$db" 2>&1 || true)
done

emit_section oracle_home_candidates
(
  (ps -ef 2>/dev/null | awk '/ora_pmon_/ {for(i=1;i<=NF;i++) if($i ~ /^ORACLE_HOME=/) {sub(/^ORACLE_HOME=/,"",$i); print $i}}' || true)
  if [ -n "$grid_home" ] && [ -n "$grid_owner" ]; then
    for db in $(printf '%s\n' "$database_list_text" | awk '{print $1}' | sed '/^$/d' | sort -u); do
      run_gi srvctl config database -d "$db" 2>/dev/null | awk -F: '/Oracle home/ {gsub(/^[[:space:]]+/,"",$2); print $2}' || true
    done
  fi
  (cat /etc/oratab 2>/dev/null | awk -F: '!/^#/ && NF>=2 {print $2}' || true)
) | sed '/^$/d' | sort -u
'''.lstrip()


def _collect_with_context(context: SharedHostContext, host: "HostConfig") -> dict[str, str]:
    sections: dict[str, str] = {}
    sections["hostname"] = context.run_cached(host, "hostname", "hostname -f 2>/dev/null || hostname 2>/dev/null").stdout
    sections["date"] = context.run_cached(host, "date", "date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true").stdout
    sections["oratab"] = context.run_cached(host, "oratab", "cat /etc/oratab 2>/dev/null || true").stdout
    sections["pmon"] = context.run_cached(host, "pmon", "ps -ef 2>/dev/null | grep -E '[o]ra_pmon_' || true").stdout
    gi_env_cmd = (
        "grid_oratab=$(awk -F: '/^\\+ASM/ {print $1 \"|\" $2; exit}' /etc/oratab 2>/dev/null || true); "
        "grid_home=; grid_owner=; "
        "if [[ \"$grid_oratab\" == *\"|\"* ]]; then grid_home=${grid_oratab#*|}; fi; "
        "if [ -n \"$grid_home\" ]; then grid_owner=$(stat -c '%U' \"$grid_home/bin/crsctl\" 2>/dev/null || true); fi; "
        "printf '%s|%s\\n' \"$grid_home\" \"$grid_owner\""
    )
    gi_env = context.run_cached(host, "db_inventory_gi_env", gi_env_cmd).stdout.strip()
    grid_home, _, grid_owner = gi_env.partition("|")
    sections["grid_home"] = grid_home
    sections["grid_owner"] = grid_owner
    db_cmd = _build_gi_command(grid_owner, grid_home, "srvctl config database") if grid_home and grid_owner else "printf '%s\\n' 'missing GRID_HOME or GRID_OWNER' >&2; exit 1"
    db_result = context.run_cached(host, "srvctl_config_database", db_cmd)
    sections["database_list"] = db_result.stdout
    sections["srvctl_database_list_returncode"] = str(db_result.returncode)
    sections["srvctl_database_list_stderr"] = db_result.stderr
    gi_cmd = _build_gi_command(grid_owner, grid_home, "crsctl query crs activeversion") if grid_home and grid_owner else "true"
    crs_cmd = _build_gi_command(grid_owner, grid_home, "crsctl stat res -t") if grid_home and grid_owner else "true"
    sections["gi_version"] = context.run_cached(host, "crsctl_activeversion", gi_cmd).stdout
    sections["crsctl_stat_res_t"] = context.run_cached(host, "crsctl_stat_res_t", crs_cmd).stdout
    databases = _parse_database_list(db_result.stdout)
    for db in databases:
        db_arg = shlex.quote(db)
        sections[f"srvctl_config_{db}"] = context.run_cached(host, f"srvctl_config_database_{db}", _build_gi_command(grid_owner, grid_home, f"srvctl config database -d {db_arg}")).stdout
        sections[f"srvctl_status_{db}"] = context.run_cached(host, f"srvctl_status_database_{db}", _build_gi_command(grid_owner, grid_home, f"srvctl status database -d {db_arg}")).stdout
    oh_cmd = "(ps -ef 2>/dev/null | awk '/ora_pmon_/ {for(i=1;i<=NF;i++) if($i ~ /^ORACLE_HOME=/) {sub(/^ORACLE_HOME=/,\"\",$i); print $i}}' || true; cat /etc/oratab 2>/dev/null | awk -F: '!/^#/ && NF>=2 {print $2}' || true) | sed '/^$/d' | sort -u"
    sections["oracle_home_candidates"] = context.run_cached(host, "oracle_home_candidates", oh_cmd).stdout
    if grid_home:
        sections["oracle_home_candidates"] = (sections["oracle_home_candidates"] + "\n" + grid_home).strip()
    return {k: v.strip() for k, v in sections.items()}


def _parse_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in output.splitlines():
        if line.startswith(SECTION_PREFIX):
            current = line.removeprefix(SECTION_PREFIX).strip()
            sections[current] = []
            continue
        if current is not None:
            if _is_prompt_line(line):
                continue
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _is_prompt_line(line: str) -> bool:
    stripped = line.strip()
    if stripped in {"$", "#", ">"}:
        return True
    return stripped.startswith("bash-") and stripped.endswith("#")



def _parse_optional_int(value: str) -> int | None:
    stripped = (value or "").strip().splitlines()[0:1]
    if not stripped or not stripped[0]:
        return None
    try:
        return int(stripped[0])
    except ValueError:
        return None


def _build_gi_command(grid_owner: str, grid_home: str, command: str) -> str:
    path = f"{grid_home}/bin:/usr/bin:/bin"
    return " ".join(
        [
            "sudo",
            "-n",
            "-u",
            shlex.quote(grid_owner),
            "env",
            f"ORACLE_HOME={shlex.quote(grid_home)}",
            f"PATH={shlex.quote(path)}",
            command,
        ]
    )

def _parse_database_list(output: str) -> list[str]:
    databases: list[str] = []
    seen: set[str] = set()
    for line in output.splitlines():
        candidate = line.strip().split()[0] if line.strip() else ""
        if not candidate:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        databases.append(candidate)
    return databases


def _parse_pmon_sids(output: str) -> list[str]:
    sids: list[str] = []
    for line in output.splitlines():
        marker = "ora_pmon_"
        if marker not in line:
            continue
        sid = line.split(marker, 1)[1].strip().split()[0]
        if sid:
            sids.append(sid)
    return sorted(set(sids))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


DB_RESOURCE_COLUMNS = [
    "HOST_NAME",
    "DB_NAME",
    "DB_ROLE",
    "OPEN_MODE",
    "VERSION",
    "RAC_ENABLED",
    "INST_COUNT",
    "SGA_TARGET_GB",
    "PGA_AGGR_TARGET_GB",
    "SGA_MAX_SIZE_GB",
    "PGA_AGGR_LIMIT_GB",
    "PROCESSES",
    "CPU_COUNT",
    "DB_SIZE_GB",
    "USED_DB_SIZE_GB",
]

_CDB_FALLBACK_ERRORS = ("ORA-00942", "ORA-01219", "ORA-01031", "PDB", "CDB")


def _parse_oracle_home_from_srvctl_config(text: str) -> str:
    """Extract Oracle home from common srvctl config database output variants."""

    patterns = [
        r"^\s*Oracle\s+home\s*:\s*(\S+)",
        r"^\s*Oracle\s+home\s+is\s+(\S+)",
        r"^\s*Database\s+home\s*:\s*(\S+)",
        r"^\s*Home\s*:\s*(\S+)",
    ]
    for line in text.splitlines():
        for pattern in patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
    return ""


def _parse_running_instances_from_srvctl_status(text: str) -> list[dict[str, str]]:
    """Parse `srvctl status database -d <db>` running instance lines."""

    instances: list[dict[str, str]] = []
    pattern = re.compile(r"Instance\s+(\S+)\s+is\s+running\s+on\s+node\s+(\S+)", re.IGNORECASE)
    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            instances.append({"sid": match.group(1).strip(), "node": match.group(2).strip(), "mapping_source": "srvctl_node_match"})
    return instances


def _select_local_instance(instances: list[dict[str, str]], host) -> dict[str, str] | None:
    """Select the running instance mapped to the current host, if any."""

    if not instances:
        return None
    candidates = _host_match_names(host)
    for instance in instances:
        node = (instance.get("node") or "").strip().lower()
        if node and node in candidates:
            selected = dict(instance)
            selected["mapping_source"] = "srvctl_node_match"
            return selected
    if len(instances) == 1:
        selected = dict(instances[0])
        selected["mapping_source"] = "single_running_instance"
        return selected
    return None


def _host_match_names(host) -> set[str]:
    values: list[str] = []
    if isinstance(host, str):
        values.append(host)
    elif isinstance(host, dict):
        values.extend(str(v) for v in host.values() if v)
    else:
        for attr in ("name", "hostname", "fqdn"):
            value = getattr(host, attr, "")
            if value:
                values.append(str(value))
    names: set[str] = set()
    for value in values:
        stripped = value.strip().lower()
        if not stripped:
            continue
        names.add(stripped)
        names.add(stripped.split(".", 1)[0])
    return names


def _build_db_resource_sql(version: str = "", use_cdb_views: bool = True) -> str:
    """Build DB resource SQL using CDB views for 12c+ and DBA views for 11g/fallback."""

    normalized_version = (version or "").strip()
    use_cdb = use_cdb_views and not normalized_version.startswith("11.2")
    data_files_view = "cdb_data_files" if use_cdb else "dba_data_files"
    segments_view = "cdb_segments" if use_cdb else "dba_segments"
    sql = f"""
WHENEVER OSERROR EXIT 9;
WHENEVER SQLERROR EXIT SQL.SQLCODE;
set pages 0 feedback off verify off heading off echo off lines 32767 trimspool on tab off
select
  (select host_name from v$instance) || '|' ||
  (select name from v$database) || '|' ||
  (select database_role from v$database) || '|' ||
  (select open_mode from v$database) || '|' ||
  (select version from v$instance) || '|' ||
  (select value from v$parameter where name='cluster_database') || '|' ||
  (select count(*) from gv$instance) || '|' ||
  round((select value from v$parameter where name='sga_target')/1024/1024/1024,2) || '|' ||
  round((select value from v$parameter where name='pga_aggregate_target')/1024/1024/1024,2) || '|' ||
  round((select value from v$parameter where name='sga_max_size')/1024/1024/1024,2) || '|' ||
  round((select value from v$parameter where name='pga_aggregate_limit')/1024/1024/1024,2) || '|' ||
  (select value from v$parameter where name='processes') || '|' ||
  (select value from v$parameter where name='cpu_count') || '|' ||
  round((select sum(bytes) from {data_files_view})/1024/1024/1024,2) || '|' ||
  round((select sum(bytes) from {segments_view})/1024/1024/1024,2)
from dual;
exit
"""
    return sql.replace("\r\n", "\n").replace("\r", "\n").lstrip()


def _parse_db_resource_sql_output(text: str) -> dict[str, str]:
    """Parse the expected 15-value pipe-delimited SQL output row."""

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("sql>") or line.startswith("-"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != len(DB_RESOURCE_COLUMNS):
            continue
        row = dict(zip(DB_RESOURCE_COLUMNS, parts, strict=True))
        rac_enabled = row.get("RAC_ENABLED", "").strip().lower()
        if rac_enabled == "true":
            row["RAC_ENABLED"] = "TRUE"
        elif rac_enabled == "false":
            row["RAC_ENABLED"] = "FALSE"
        return row
    raise ValueError("Expected 15 pipe-delimited DB resource values")



def _collect_pmon_oratab_fallback_details(
    runner: SSHRunner | None,
    host,
    cluster: str,
    host_name: str,
    address: str,
    collected_at: str,
    pmon_sids: list[str],
    oratab: str,
    remote_hostname: str = "",
    logger: logging.Logger | None = None,
    sql_executor=None,
) -> list[dict[str, object]]:
    """Collect DB resource rows for local PMON instances when srvctl database listing fails."""

    details: list[dict[str, object]] = []
    sid_home_map = _parse_oratab_sid_home_map(oratab)
    for sid in pmon_sids:
        oracle_home = _lookup_oratab_home_for_sid(sid, sid_home_map)
        db_unique_name = _db_unique_from_sid(sid)
        base = _db_resource_base_record(cluster, host_name, address, collected_at, db_unique_name, oracle_home)
        base.update({"oracle_sid": sid, "mapping_source": "pmon_oratab_fallback", "source": "pmon_oratab_fallback"})
        if not oracle_home:
            base.update({"collection_status": "failed", "collection_error": "oracle_home_not_found", "error_category": "UNKNOWN"})
            details.append(base)
            continue
        result = _execute_db_resource_sql(runner, host, oracle_home, sid, "", True, sql_executor)
        size_source = "cdb"
        if (not result.ok) and _should_fallback_to_dba(result.stderr + "\n" + result.stdout):
            result = _execute_db_resource_sql(runner, host, oracle_home, sid, "", False, sql_executor)
            size_source = "dba_fallback"
        base.update({"sql_returncode": result.returncode, "sql_stdout": result.stdout.strip(), "sql_stderr": result.stderr.strip(), "size_source": size_source})
        if not result.ok:
            base.update({"collection_status": "failed", "collection_error": _sql_failure_error(result, host_name), "error_category": _sql_error_category(result.stdout, result.stderr, result.returncode)})
            details.append(base)
            if logger:
                logger.warning("DB resource SQL fallback failed for %s/%s: %s", db_unique_name, sid, base["collection_error"])
            continue
        try:
            parsed = _parse_db_resource_sql_output(result.stdout)
        except ValueError as exc:
            base.update({"collection_status": "failed", "collection_error": str(exc), "error_category": "UNKNOWN"})
            details.append(base)
            continue
        base.update(parsed)
        base.update({"collection_status": "success", "collection_error": "", "error_category": ""})
        details.append(base)
    return details


def _parse_oratab_sid_home_map(oratab: str) -> dict[str, str]:
    sid_home: dict[str, str] = {}
    for line in oratab.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(":")
        if len(parts) < 2:
            continue
        sid, home = parts[0].strip(), parts[1].strip()
        if sid and home:
            sid_home[sid] = home
    return sid_home


def _lookup_oratab_home_for_sid(sid: str, sid_home_map: dict[str, str]) -> str:
    candidates = [sid, _db_unique_from_sid(sid)]
    for candidate in candidates:
        if candidate in sid_home_map:
            return sid_home_map[candidate]
    return ""


def _db_unique_from_sid(sid: str) -> str:
    return re.sub(r"(?:_?\d+)$", "", sid)

def _collect_db_resource_details(
    runner: SSHRunner | None,
    host,
    cluster: str,
    host_name: str,
    address: str,
    collected_at: str,
    databases: list[str],
    srvctl_config: dict[str, str],
    srvctl_status: dict[str, str],
    oracle_home_candidates: list[str],
    remote_hostname: str = "",
    logger: logging.Logger | None = None,
    sql_executor=None,
) -> list[dict[str, object]]:
    """Collect one flattened DB resource record per srvctl-discovered database."""

    details: list[dict[str, object]] = []
    host_identity = {"inventory_name": host_name, "hostname": remote_hostname.strip().splitlines()[0] if remote_hostname.strip() else ""}
    for db_unique_name in databases:
        config_text = srvctl_config.get(db_unique_name, "")
        status_text = srvctl_status.get(db_unique_name, "")
        oracle_home = _parse_oracle_home_from_srvctl_config(config_text)
        if not oracle_home and oracle_home_candidates:
            oracle_home = oracle_home_candidates[0]
        instances = _parse_running_instances_from_srvctl_status(status_text)
        selected = _select_local_instance(instances, host_identity)
        base = _db_resource_base_record(cluster, host_name, address, collected_at, db_unique_name, oracle_home)
        if selected is None:
            base.update({"collection_status": "skipped", "collection_error": "no_local_running_instance", "error_category": "NO_LOCAL_INSTANCE"})
            details.append(base)
            continue
        sid = selected.get("sid", "")
        base.update({"oracle_sid": sid, "mapping_source": selected.get("mapping_source", "")})
        if not oracle_home:
            base.update({"collection_status": "failed", "collection_error": "oracle_home_not_found", "error_category": "UNKNOWN"})
            details.append(base)
            continue

        version_hint = _parse_version_hint(config_text)
        first_use_cdb = not version_hint.startswith("11.2")
        result = _execute_db_resource_sql(runner, host, oracle_home, sid, version_hint, first_use_cdb, sql_executor)
        size_source = "cdb" if first_use_cdb else "dba"
        if first_use_cdb and (not result.ok) and _should_fallback_to_dba(result.stderr + "\n" + result.stdout):
            result = _execute_db_resource_sql(runner, host, oracle_home, sid, version_hint, False, sql_executor)
            size_source = "dba_fallback"
        base.update({"sql_returncode": result.returncode, "sql_stdout": result.stdout.strip(), "sql_stderr": result.stderr.strip(), "size_source": size_source})
        if not result.ok:
            base.update({"collection_status": "failed", "collection_error": _sql_failure_error(result, host_name), "error_category": _sql_error_category(result.stdout, result.stderr, result.returncode)})
            details.append(base)
            if logger:
                logger.warning("DB resource SQL failed for %s/%s: %s", db_unique_name, sid, base["collection_error"])
            continue
        try:
            parsed = _parse_db_resource_sql_output(result.stdout)
        except ValueError as exc:
            base.update({"collection_status": "failed", "collection_error": str(exc), "error_category": "UNKNOWN"})
            details.append(base)
            continue
        base.update(parsed)
        base.update({"collection_status": "success", "collection_error": "", "error_category": ""})
        details.append(base)
    return details


def _db_resource_base_record(cluster: str, host: str, address: str, collected_at: str, db_unique_name: str, oracle_home: str) -> dict[str, object]:
    row: dict[str, object] = {column: "" for column in DB_RESOURCE_COLUMNS}
    row.update(
        {
            "Cluster": cluster,
            "cluster": cluster,
            "host": host,
            "address": address,
            "db_unique_name": db_unique_name,
            "oracle_home": oracle_home,
            "oracle_sid": "",
            "size_source": "",
            "collection_status": "",
            "collection_error": "",
            "error_category": "",
            "sql_returncode": "",
            "sql_stdout": "",
            "sql_stderr": "",
            "Collected_At": collected_at,
            "mapping_source": "",
        }
    )
    return row


def _parse_version_hint(text: str) -> str:
    for line in text.splitlines():
        match = re.search(r"(?:Database\s+)?Version\s*:\s*([0-9][^\s]*)", line, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _execute_db_resource_sql(runner: SSHRunner | None, host, oracle_home: str, sid: str, version: str, use_cdb_views: bool, sql_executor=None):
    sql = _build_db_resource_sql(version, use_cdb_views).replace("\r\n", "\n").replace("\r", "\n")
    if sql_executor is not None:
        return sql_executor(oracle_home, sid, sql, use_cdb_views)
    if runner is None:
        raise ValueError("runner is required when sql_executor is not supplied")
    command = _build_sqlplus_command(oracle_home, sid)
    ssh_command = [*runner._build_ssh_command(host, allocate_tty=getattr(host, "force_tty", False)), command]
    return runner._run(ssh_command, host, sql)


def _build_sqlplus_command(oracle_home: str, sid: str) -> str:
    path = f"{oracle_home}/bin:/usr/bin:/bin"
    return " ".join(
        [
            "sudo",
            "-n",
            "-u",
            "oracle",
            "env",
            f"ORACLE_HOME={shlex.quote(oracle_home)}",
            f"ORACLE_SID={shlex.quote(sid)}",
            f"PATH={shlex.quote(path)}",
            "timeout",
            "60s",
            "sqlplus",
            "-s",
            "/",
            "as",
            "sysdba",
        ]
    )


def _should_fallback_to_dba(output: str) -> bool:
    upper = output.upper()
    return any(marker in upper for marker in _CDB_FALLBACK_ERRORS)


_ORACLE_MESSAGE_PATTERN = re.compile(r"\b(ORA-\d{5}|SP2-\d{4}|TNS-\d{5})\b[^\r\n]*", re.IGNORECASE)


def _extract_sql_error_messages(stdout: str = "", stderr: str = "") -> list[str]:
    """Extract Oracle/sqlplus/TNS diagnostic lines from stdout and stderr."""

    messages: list[str] = []
    seen: set[str] = set()
    for text in (stdout or "", stderr or ""):
        for match in _ORACLE_MESSAGE_PATTERN.finditer(text):
            message = match.group(0).strip()
            key = message.upper()
            if message and key not in seen:
                seen.add(key)
                messages.append(message)
    return messages


def _is_connection_closed_noise(text: str, host_name: str = "") -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return True
    pattern = re.compile(r"^Connection to .+ closed\.?$", re.IGNORECASE)
    return all(pattern.match(line) for line in lines)


def _sql_error_category(stdout: str = "", stderr: str = "", returncode: int | None = None, host_name: str = "") -> str:
    combined = f"{stdout or ''}\n{stderr or ''}"
    upper = combined.upper()
    if "ORA-" in upper:
        return "ORACLE_ERROR"
    if "SP2-" in upper:
        return "SQLPLUS_ERROR"
    if "TNS-" in upper:
        return "TNS_ERROR"
    if stderr and not _is_connection_closed_noise(stderr, host_name):
        return "SSH_ERROR"
    if returncode not in (None, 0):
        return "UNKNOWN"
    return "UNKNOWN"


def _sql_failure_error(result, host_name: str = "") -> str:
    oracle_messages = _extract_sql_error_messages(result.stdout, result.stderr)
    if oracle_messages:
        return " | ".join(oracle_messages)

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    detail = ""
    if stderr and not _is_connection_closed_noise(stderr, host_name):
        detail = stderr
    elif stdout:
        detail = stdout
    elif stderr:
        detail = stderr
    else:
        detail = f"sqlplus exited with {result.returncode}"

    if "sudo" in detail.lower() and ("password" in detail.lower() or "not allowed" in detail.lower() or "a password is required" in detail.lower()):
        return f"{detail}; configure NOPASSWD sudo for the service account"
    return detail
