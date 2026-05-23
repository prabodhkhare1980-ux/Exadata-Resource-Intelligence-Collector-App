"""Oracle RAC / DB inventory collector."""

from __future__ import annotations

import json
import logging
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
        logger.debug("Authoritative srvctl DB list: %s", databases)
        logger.debug("PMON SID list: %s", pmon_sids)
        logger.debug("srvctl loop source=srvctl_config_database")
        srvctl_config = {db: sections.get(f"srvctl_config_{db}", "") for db in databases}
        srvctl_status = {db: sections.get(f"srvctl_status_{db}", "") for db in databases}

        record = DBInventoryRecord(
            cluster=cluster_name,
            host=host.name,
            address=host.address,
            collected_at=collected_at,
            status="ok",
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
            oracle_home_candidates=[line.strip() for line in sections.get("oracle_home_candidates", "").splitlines() if line.strip()],
            raw=sections,
        )
        logger.info("Completed DB inventory collection for %s", host.name)
        return record


DB_INVENTORY_SCRIPT = r'''
set -o pipefail
emit_section() {
  printf '\n__ERIC_SECTION__:%s\n' "$1"
}

emit_section hostname
(hostname -f 2>/dev/null || hostname 2>/dev/null) || true

emit_section date
date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true

emit_section oratab
(cat /etc/oratab 2>/dev/null || true)

emit_section pmon
(ps -ef 2>/dev/null | grep -E '[o]ra_pmon_' || true)

emit_section database_list
(srvctl config database 2>/dev/null | awk '{print $1}' | sed '/^$/d' | sort -u || true)

grid_home="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"
if [ -n "$grid_home" ]; then
  export ORACLE_HOME="$grid_home"
  export PATH="$ORACLE_HOME/bin:$PATH"
fi

emit_section gi_version
(crsctl query crs activeversion 2>&1 || true)

emit_section crsctl_stat_res_t
(crsctl stat res -t 2>&1 || true)

for db in $(srvctl config database 2>/dev/null | awk '{print $1}' | sed '/^$/d' | sort -u); do
  emit_section "srvctl_config_${db}"
  (srvctl config database -d "$db" 2>&1 || true)
  emit_section "srvctl_status_${db}"
  (srvctl status database -d "$db" 2>&1 || true)
done

emit_section oracle_home_candidates
(
  (ps -ef 2>/dev/null | awk '/ora_pmon_/ {for(i=1;i<=NF;i++) if($i ~ /^ORACLE_HOME=/) {sub(/^ORACLE_HOME=/,"",$i); print $i}}' || true)
  (srvctl config database 2>/dev/null | awk -F: '/Oracle home/ {gsub(/^[[:space:]]+/,"",$2); print $2}' || true)
  (cat /etc/oratab 2>/dev/null | awk -F: '!/^#/ && NF>=2 {print $2}' || true)
) | sed '/^$/d' | sort -u
'''.lstrip()


def _collect_with_context(context: SharedHostContext, host: "HostConfig") -> dict[str, str]:
    sections: dict[str, str] = {}
    sections["hostname"] = context.run_cached(host, "hostname", "hostname -f 2>/dev/null || hostname 2>/dev/null").stdout
    sections["date"] = context.run_cached(host, "date", "date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true").stdout
    sections["oratab"] = context.run_cached(host, "oratab", "cat /etc/oratab 2>/dev/null || true").stdout
    sections["pmon"] = context.run_cached(host, "pmon", "ps -ef 2>/dev/null | grep -E '[o]ra_pmon_' || true").stdout
    db_list = context.run_cached(host, "srvctl_config_database", "srvctl config database 2>/dev/null | awk '{print $1}' | sed '/^$/d' | sort -u || true").stdout
    sections["database_list"] = db_list
    gi_cmd = """grid_home="$(awk -F: '/^\\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"; if [ -n "$grid_home" ]; then export ORACLE_HOME="$grid_home"; export PATH="$ORACLE_HOME/bin:$PATH"; fi; crsctl query crs activeversion 2>&1 || true"""
    crs_cmd = """grid_home="$(awk -F: '/^\\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"; if [ -n "$grid_home" ]; then export ORACLE_HOME="$grid_home"; export PATH="$ORACLE_HOME/bin:$PATH"; fi; crsctl stat res -t 2>&1 || true"""
    sections["gi_version"] = context.run_cached(host, "crsctl_activeversion", gi_cmd).stdout
    sections["crsctl_stat_res_t"] = context.run_cached(host, "crsctl_stat_res_t", crs_cmd).stdout
    databases = _parse_database_list(db_list)
    for db in databases:
        sections[f"srvctl_config_{db}"] = context.run_cached(host, f"srvctl_config_database_{db}", f"srvctl config database -d '{db}' 2>&1 || true").stdout
        sections[f"srvctl_status_{db}"] = context.run_cached(host, f"srvctl_status_database_{db}", f"srvctl status database -d '{db}' 2>&1 || true").stdout
    gi_home = context.run_cached(host, "gi_home_discovery", """awk -F: '/^\\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null || true""").stdout.strip()
    oh_cmd = """(ps -ef 2>/dev/null | awk '/ora_pmon_/ {for(i=1;i<=NF;i++) if($i ~ /^ORACLE_HOME=/) {sub(/^ORACLE_HOME=/,"",$i); print $i}}' || true; cat /etc/oratab 2>/dev/null | awk -F: '!/^#/ && NF>=2 {print $2}' || true) | sed '/^$/d' | sort -u"""
    sections["oracle_home_candidates"] = context.run_cached(host, "oracle_home_candidates", oh_cmd).stdout
    if gi_home:
        sections["oracle_home_candidates"] = (sections["oracle_home_candidates"] + "\n" + gi_home).strip()
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
