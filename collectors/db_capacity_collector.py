"""License- and capacity-oriented DB collectors built on the DB inventory.

This module adds three SQL collections a DMA needs for license posture and
capacity assessment, none of which the original collectors captured:

* **PDB inventory** (``v$pdbs`` + ``cdb_data_files``): one row per pluggable
  database with open mode, restricted flag, and total size. Multitenant
  license exposure is driven by PDB counts, so this is collected per CDB.
* **Feature usage** (``dba_feature_usage_statistics``): currently-used,
  license-relevant options/features (Partitioning, Advanced Compression,
  RAT, In-Memory, Active Data Guard, etc.). One row per feature.

Both reuse the DB-inventory SQL execution plumbing (sqlplus over SSH as the
DB home owner) via :func:`collectors.db_performance_collector._execute_sql`,
and both iterate only databases the DB inventory already proved are open and
locally running on the host.

These views require only the base database (no Diagnostics Pack), unlike the
AWR collectors.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from collectors.db_inventory_collector import DBInventoryRecord, _sql_failure_error
from collectors.db_performance_collector import (
    _db_perf_error_category,
    _execute_sql,
    _local_success_db_details,
)
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

PDB_INVENTORY_SQL_COLUMNS = [
    "CDB_NAME",
    "PDB_NAME",
    "CON_ID",
    "OPEN_MODE",
    "RESTRICTED",
    "TOTAL_SIZE_GB",
]

PDB_INVENTORY_COLUMNS = [
    "Cluster",
    "HOST_NAME",
    *PDB_INVENTORY_SQL_COLUMNS,
    "Collected_At",
    "db_unique_name",
    "source_host",
    "source_address",
    "source_oracle_sid",
    "collection_status",
    "collection_error",
    "error_category",
]

FEATURE_USAGE_SQL_COLUMNS = [
    "DB_NAME",
    "FEATURE_NAME",
    "CURRENTLY_USED",
    "DETECTED_USAGES",
    "FIRST_USAGE_DATE",
    "LAST_USAGE_DATE",
]

FEATURE_USAGE_COLUMNS = [
    "Cluster",
    "HOST_NAME",
    *FEATURE_USAGE_SQL_COLUMNS,
    "Collected_At",
    "db_unique_name",
    "source_host",
    "source_address",
    "source_oracle_sid",
    "collection_status",
    "collection_error",
    "error_category",
]


@dataclass
class PDBInventoryRecord:
    Cluster: str
    HOST_NAME: str
    CDB_NAME: str = ""
    PDB_NAME: str = ""
    CON_ID: str = ""
    OPEN_MODE: str = ""
    RESTRICTED: str = ""
    TOTAL_SIZE_GB: str = ""
    Collected_At: str = ""
    db_unique_name: str = ""
    source_host: str = ""
    source_address: str = ""
    source_oracle_sid: str = ""
    collection_status: str = "success"
    collection_error: str = ""
    error_category: str = ""
    oracle_home: str = ""
    oracle_sid: str = ""
    sql_returncode: int | str = ""
    sql_stdout: str = ""
    sql_stderr: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return {column: getattr(self, column) for column in PDB_INVENTORY_COLUMNS}

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class FeatureUsageRecord:
    Cluster: str
    HOST_NAME: str
    DB_NAME: str = ""
    FEATURE_NAME: str = ""
    CURRENTLY_USED: str = ""
    DETECTED_USAGES: str = ""
    FIRST_USAGE_DATE: str = ""
    LAST_USAGE_DATE: str = ""
    Collected_At: str = ""
    db_unique_name: str = ""
    source_host: str = ""
    source_address: str = ""
    source_oracle_sid: str = ""
    collection_status: str = "success"
    collection_error: str = ""
    error_category: str = ""
    oracle_home: str = ""
    oracle_sid: str = ""
    sql_returncode: int | str = ""
    sql_stdout: str = ""
    sql_stderr: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return {column: getattr(self, column) for column in FEATURE_USAGE_COLUMNS}

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------

_SQL_HEADER = (
    "WHENEVER OSERROR EXIT 9;\n"
    "WHENEVER SQLERROR EXIT SQL.SQLCODE;\n"
    "set echo off\n"
    "set termout off\n"
    "set feedback off\n"
    "set heading off\n"
    "set verify off\n"
    "set pages 0\n"
    "set lines 32767\n"
    "set trimspool on\n"
    "set tab off\n"
)


def build_pdb_inventory_sql() -> str:
    """Return SQL emitting one pipe-delimited row per non-seed PDB.

    ``con_id > 2`` excludes ``CDB$ROOT`` (1) and ``PDB$SEED`` (2). On a
    non-CDB the ``v$pdbs`` view exists (12c+) but returns no rows, so the
    output is legitimately empty. On 11g ``v$pdbs`` does not exist and the
    statement raises ORA-00942, which the collector records as an error.
    """

    return (
        _SQL_HEADER
        + """
SELECT (SELECT name FROM v$database) || '|' ||
       p.name || '|' ||
       p.con_id || '|' ||
       p.open_mode || '|' ||
       p.restricted || '|' ||
       nvl(round(c.bytes/1024/1024/1024, 2), 0)
FROM v$pdbs p
LEFT JOIN (
  SELECT con_id, SUM(bytes) bytes FROM cdb_data_files GROUP BY con_id
) c ON c.con_id = p.con_id
WHERE p.con_id > 2
ORDER BY p.con_id;
exit
"""
    ).lstrip()


def build_feature_usage_sql() -> str:
    """Return SQL emitting one row per currently-used database feature.

    Uses the most recent sample per feature (``dba_feature_usage_statistics``
    accumulates a row per feature per sample window) and reports only
    features whose latest sample has ``currently_used = 'TRUE'`` — the
    actionable, license-relevant set.
    """

    return (
        _SQL_HEADER
        + """
SELECT db_name || '|' ||
       feature_name || '|' ||
       currently_used || '|' ||
       nvl(to_char(detected_usages), '0') || '|' ||
       nvl(to_char(first_usage_date, 'YYYY-MM-DD'), '') || '|' ||
       nvl(to_char(last_usage_date, 'YYYY-MM-DD'), '')
FROM (
  SELECT (SELECT name FROM v$database) db_name,
         f.name feature_name,
         f.currently_used,
         f.detected_usages,
         f.first_usage_date,
         f.last_usage_date,
         ROW_NUMBER() OVER (
           PARTITION BY f.name ORDER BY f.last_sample_date DESC NULLS LAST
         ) rn
  FROM dba_feature_usage_statistics f
)
WHERE rn = 1
  AND currently_used = 'TRUE'
ORDER BY feature_name;
exit
"""
    ).lstrip()


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

_SQL_ECHO_PREFIXES = (
    "whenever",
    "set",
    "select",
    "from",
    "left join",
    "where",
    "order by",
    "exit",
    "group by",
)


def _parse_pipe_rows(text: str, columns: list[str]) -> list[dict[str, str]]:
    """Parse pipe-delimited rows, tolerating an empty (no-rows) result.

    Unlike the AWR parsers this does NOT raise when there are zero data
    rows: a non-CDB legitimately has no PDBs, and a database may use no
    tracked features. Callers distinguish "ran fine, nothing to report"
    from "failed" via the SQL return code.
    """

    expected_delimiters = len(columns) - 1
    rows: list[dict[str, str]] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if (
            not line
            or lower.startswith("sql>")
            or line.startswith("-")
            or lower.startswith(_SQL_ECHO_PREFIXES)
        ):
            continue
        if line.count("|") != expected_delimiters:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != len(columns):
            continue
        rows.append(dict(zip(columns, parts, strict=True)))
    return rows


def parse_pdb_inventory_output(text: str) -> list[dict[str, str]]:
    return _parse_pipe_rows(text, PDB_INVENTORY_SQL_COLUMNS)


def parse_feature_usage_output(text: str) -> list[dict[str, str]]:
    return _parse_pipe_rows(text, FEATURE_USAGE_SQL_COLUMNS)


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DBCapacityCollector:
    """Collect PDB inventory and feature usage for locally-open databases."""

    def __init__(
        self, runner: SSHRunner | None, logger: logging.Logger | None = None
    ) -> None:
        self.runner = runner
        self.logger = logger or logging.getLogger(__name__)

    def collect_host(
        self,
        db_inventory: DBInventoryRecord,
        host: "HostConfig",
        *,
        enabled: bool = True,
        collect_pdb_inventory: bool = True,
        collect_feature_usage: bool = True,
        timeout_seconds: int = 90,
        sql_executor=None,
    ) -> tuple[list[PDBInventoryRecord], list[FeatureUsageRecord]]:
        if not enabled:
            return [], []

        pdb_records: list[PDBInventoryRecord] = []
        feature_records: list[FeatureUsageRecord] = []
        now = _utc_now()

        for detail in _local_success_db_details(db_inventory.db_resource_details):
            db_unique_name = str(
                detail.get("db_unique_name") or detail.get("DB_NAME") or ""
            )
            oracle_home = str(detail.get("oracle_home") or "")
            oracle_sid = str(detail.get("oracle_sid") or "")
            if collect_pdb_inventory:
                pdb_records.extend(
                    self._collect_pdb_inventory(
                        db_inventory, host, db_unique_name, oracle_home,
                        oracle_sid, timeout_seconds, now, sql_executor,
                    )
                )
            if collect_feature_usage:
                feature_records.extend(
                    self._collect_feature_usage(
                        db_inventory, host, db_unique_name, oracle_home,
                        oracle_sid, timeout_seconds, now, sql_executor,
                    )
                )
        return pdb_records, feature_records

    def _collect_pdb_inventory(
        self, inv, host, db_unique_name, oracle_home, oracle_sid,
        timeout_seconds, collected_at, sql_executor,
    ) -> list[PDBInventoryRecord]:
        result = _execute_sql(
            self.runner, host, oracle_home, oracle_sid,
            build_pdb_inventory_sql(), timeout_seconds, sql_executor, "pdb_inventory",
        )
        if not result.ok:
            return [
                self._failed_pdb(
                    inv, db_unique_name, oracle_home, oracle_sid, collected_at,
                    _sql_failure_error(result, inv.host),
                    _db_perf_error_category(
                        result.stdout, result.stderr, getattr(result, "error", "")
                    ),
                    result,
                )
            ]
        rows = parse_pdb_inventory_output(result.stdout)
        if not rows:
            # Ran cleanly, but no PDBs (non-CDB or empty CDB). Record a
            # single informational row so the DB still appears in output.
            return [
                PDBInventoryRecord(
                    Cluster=inv.cluster,
                    HOST_NAME=inv.host,
                    CDB_NAME=db_unique_name,
                    Collected_At=collected_at,
                    source_host=inv.host,
                    source_address=inv.address,
                    source_oracle_sid=oracle_sid,
                    db_unique_name=db_unique_name,
                    oracle_home=oracle_home,
                    oracle_sid=oracle_sid,
                    collection_status="success",
                    collection_error="no_pluggable_databases",
                )
            ]
        return [
            PDBInventoryRecord(
                Cluster=inv.cluster,
                HOST_NAME=inv.host,
                Collected_At=collected_at,
                source_host=inv.host,
                source_address=inv.address,
                source_oracle_sid=oracle_sid,
                db_unique_name=db_unique_name,
                oracle_home=oracle_home,
                oracle_sid=oracle_sid,
                **row,
            )
            for row in rows
        ]

    def _collect_feature_usage(
        self, inv, host, db_unique_name, oracle_home, oracle_sid,
        timeout_seconds, collected_at, sql_executor,
    ) -> list[FeatureUsageRecord]:
        result = _execute_sql(
            self.runner, host, oracle_home, oracle_sid,
            build_feature_usage_sql(), timeout_seconds, sql_executor, "feature_usage",
        )
        if not result.ok:
            return [
                self._failed_feature(
                    inv, db_unique_name, oracle_home, oracle_sid, collected_at,
                    _sql_failure_error(result, inv.host),
                    _db_perf_error_category(
                        result.stdout, result.stderr, getattr(result, "error", "")
                    ),
                    result,
                )
            ]
        rows = parse_feature_usage_output(result.stdout)
        if not rows:
            return [
                FeatureUsageRecord(
                    Cluster=inv.cluster,
                    HOST_NAME=inv.host,
                    DB_NAME=db_unique_name,
                    Collected_At=collected_at,
                    source_host=inv.host,
                    source_address=inv.address,
                    source_oracle_sid=oracle_sid,
                    db_unique_name=db_unique_name,
                    oracle_home=oracle_home,
                    oracle_sid=oracle_sid,
                    collection_status="success",
                    collection_error="no_tracked_features",
                )
            ]
        return [
            FeatureUsageRecord(
                Cluster=inv.cluster,
                HOST_NAME=inv.host,
                Collected_At=collected_at,
                source_host=inv.host,
                source_address=inv.address,
                source_oracle_sid=oracle_sid,
                db_unique_name=db_unique_name,
                oracle_home=oracle_home,
                oracle_sid=oracle_sid,
                **row,
            )
            for row in rows
        ]

    def _failed_pdb(
        self, inv, db_unique_name, oracle_home, oracle_sid, collected_at,
        error, category, result=None,
    ) -> PDBInventoryRecord:
        return PDBInventoryRecord(
            Cluster=inv.cluster,
            HOST_NAME=inv.host,
            CDB_NAME=db_unique_name,
            Collected_At=collected_at,
            source_host=inv.host,
            source_address=inv.address,
            source_oracle_sid=oracle_sid,
            db_unique_name=db_unique_name,
            oracle_home=oracle_home,
            oracle_sid=oracle_sid,
            collection_status="failed",
            collection_error=error,
            error_category=category,
            sql_returncode=getattr(result, "returncode", "") if result else "",
            sql_stdout=getattr(result, "stdout", "") if result else "",
            sql_stderr=getattr(result, "stderr", "") if result else "",
        )

    def _failed_feature(
        self, inv, db_unique_name, oracle_home, oracle_sid, collected_at,
        error, category, result=None,
    ) -> FeatureUsageRecord:
        return FeatureUsageRecord(
            Cluster=inv.cluster,
            HOST_NAME=inv.host,
            DB_NAME=db_unique_name,
            Collected_At=collected_at,
            source_host=inv.host,
            source_address=inv.address,
            source_oracle_sid=oracle_sid,
            db_unique_name=db_unique_name,
            oracle_home=oracle_home,
            oracle_sid=oracle_sid,
            collection_status="failed",
            collection_error=error,
            error_category=category,
            sql_returncode=getattr(result, "returncode", "") if result else "",
            sql_stdout=getattr(result, "stdout", "") if result else "",
            sql_stderr=getattr(result, "stderr", "") if result else "",
        )
