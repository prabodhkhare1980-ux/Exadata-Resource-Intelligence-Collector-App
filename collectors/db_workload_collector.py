"""AWR workload-intensity and tablespace-growth collector.

Adds the capacity-assessment signals the IOPS/CPU collector left out:

* **Workload intensity** per AWR snapshot: DB Time, DB CPU, Average Active
  Sessions (AAS), and redo generation rate. AAS is the single most useful
  capacity metric (it expresses load in CPU-equivalent terms), and redo
  rate drives standby sizing and archive storage growth. Derived from
  snapshot-to-snapshot deltas of ``dba_hist_sys_time_model`` (DB time / DB
  CPU) and ``dba_hist_sysstat`` ('redo size').

* **Tablespace growth** per AWR snapshot: allocated and used GB per
  tablespace over time, from ``dba_hist_tbspc_space_usage``. This is what
  makes per-tablespace days-to-full / growth-rate analytics possible.

Like :mod:`collectors.db_performance_collector` this reads ``DBA_HIST_*``
views and therefore requires Oracle Diagnostics Pack licensing. It reuses
that module's sqlplus-over-SSH execution and local-DB iteration helpers.
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
    _parse_pipe_rows,
)
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

WORKLOAD_SQL_COLUMNS = [
    "DB_NAME",
    "INSTANCE_NAME",
    "END_TIME",
    "ELAPSED_SEC",
    "DB_TIME_SEC",
    "DB_CPU_SEC",
    "AAS",
    "REDO_MB",
    "REDO_MBPS",
]

WORKLOAD_COLUMNS = [
    "Cluster",
    "HOST_NAME",
    *WORKLOAD_SQL_COLUMNS,
    "Collected_At",
    "db_unique_name",
    "source_host",
    "source_address",
    "source_oracle_sid",
    "collection_status",
    "collection_error",
    "error_category",
]

TABLESPACE_GROWTH_SQL_COLUMNS = [
    "DB_NAME",
    "TABLESPACE_NAME",
    "SNAP_TIME",
    "ALLOC_GB",
    "USED_GB",
    "USED_PCT_OF_MAX",
]

TABLESPACE_GROWTH_COLUMNS = [
    "Cluster",
    "HOST_NAME",
    *TABLESPACE_GROWTH_SQL_COLUMNS,
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
class DBWorkloadRecord:
    Cluster: str
    HOST_NAME: str
    DB_NAME: str = ""
    INSTANCE_NAME: str = ""
    END_TIME: str = ""
    ELAPSED_SEC: str = ""
    DB_TIME_SEC: str = ""
    DB_CPU_SEC: str = ""
    AAS: str = ""
    REDO_MB: str = ""
    REDO_MBPS: str = ""
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
        return {column: getattr(self, column) for column in WORKLOAD_COLUMNS}

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class DBTablespaceGrowthRecord:
    Cluster: str
    HOST_NAME: str
    DB_NAME: str = ""
    TABLESPACE_NAME: str = ""
    SNAP_TIME: str = ""
    ALLOC_GB: str = ""
    USED_GB: str = ""
    USED_PCT_OF_MAX: str = ""
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
        return {column: getattr(self, column) for column in TABLESPACE_GROWTH_COLUMNS}

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------

_SQL_HEADER = """WHENEVER OSERROR EXIT 9;
WHENEVER SQLERROR EXIT SQL.SQLCODE;
set echo off
set termout off
set feedback off
set heading off
set verify off
set pages 0
set lines 32767
set trimspool on
set tab off
alter session set nls_date_format='YYYY-MM-DD HH24:MI:SS';
"""


def build_db_workload_sql(days_back: int) -> str:
    """Per-snapshot DB Time / DB CPU / AAS / redo rate from AWR deltas.

    Cumulative time-model and sysstat counters are differenced against the
    previous snapshot for the same instance (LAG over snap_id). Rows where
    the delta is negative (instance restart / counter reset) or where there
    is no prior snapshot are dropped. AAS = DB-time-seconds / elapsed-seconds.
    """

    days = max(int(days_back), 1)
    return _SQL_HEADER + f"""define DAYS_BACK={days}

WITH tm AS (
  SELECT s.snap_id, s.instance_number, s.dbid,
         s.end_interval_time,
         m.stat_name, m.value
  FROM dba_hist_sys_time_model m
  JOIN dba_hist_snapshot s
    ON s.snap_id = m.snap_id
   AND s.instance_number = m.instance_number
   AND s.dbid = m.dbid
  WHERE m.stat_name IN ('DB time', 'DB CPU')
    AND s.end_interval_time >= SYSDATE - &&DAYS_BACK
),
tm_piv AS (
  SELECT snap_id, instance_number, dbid, end_interval_time,
         MAX(DECODE(stat_name, 'DB time', value)) db_time,
         MAX(DECODE(stat_name, 'DB CPU', value)) db_cpu
  FROM tm
  GROUP BY snap_id, instance_number, dbid, end_interval_time
),
redo AS (
  SELECT snap_id, instance_number, dbid, value redo_value
  FROM dba_hist_sysstat
  WHERE stat_name = 'redo size'
),
j AS (
  SELECT p.snap_id, p.instance_number, p.end_interval_time,
         p.db_time, p.db_cpu, r.redo_value,
         LAG(p.db_time) OVER (PARTITION BY p.instance_number, p.dbid ORDER BY p.snap_id) prev_db_time,
         LAG(p.db_cpu)  OVER (PARTITION BY p.instance_number, p.dbid ORDER BY p.snap_id) prev_db_cpu,
         LAG(r.redo_value) OVER (PARTITION BY p.instance_number, p.dbid ORDER BY p.snap_id) prev_redo,
         LAG(p.end_interval_time) OVER (PARTITION BY p.instance_number, p.dbid ORDER BY p.snap_id) prev_end
  FROM tm_piv p
  LEFT JOIN redo r
    ON r.snap_id = p.snap_id AND r.instance_number = p.instance_number AND r.dbid = p.dbid
)
SELECT (SELECT name FROM v$database) || '|' ||
       (SELECT instance_name FROM gv$instance i WHERE i.instance_number = j.instance_number AND ROWNUM = 1) || '|' ||
       to_char(end_interval_time, 'YYYY-MM-DD HH24:MI:SS') || '|' ||
       round(elapsed_sec, 0) || '|' ||
       round(db_time_sec, 1) || '|' ||
       round(db_cpu_sec, 1) || '|' ||
       round(db_time_sec / nullif(elapsed_sec, 0), 2) || '|' ||
       round(redo_mb, 1) || '|' ||
       round(redo_mb / nullif(elapsed_sec, 0), 3)
FROM (
  SELECT j.*,
         (CAST(end_interval_time AS DATE) - CAST(prev_end AS DATE)) * 86400 elapsed_sec,
         (db_time - prev_db_time) / 1000000 db_time_sec,
         (db_cpu - prev_db_cpu) / 1000000 db_cpu_sec,
         (redo_value - prev_redo) / 1024 / 1024 redo_mb
  FROM j
  WHERE prev_db_time IS NOT NULL
    AND db_time >= prev_db_time
) j
WHERE elapsed_sec > 0
ORDER BY instance_number, end_interval_time;
exit
"""


def build_db_tablespace_growth_sql(days_back: int) -> str:
    """Per-snapshot per-tablespace allocated/used GB from AWR.

    ``dba_hist_tbspc_space_usage`` stores sizes in blocks; we approximate
    with ``db_block_size`` (the default block size most tablespaces use).
    ``tablespace_maxsize`` is 0 when a tablespace has no autoextend max, so
    the used-pct-of-max guards with NULLIF.
    """

    days = max(int(days_back), 1)
    return _SQL_HEADER + f"""define DAYS_BACK={days}

SELECT (SELECT name FROM v$database) || '|' ||
       ts.name || '|' ||
       to_char(to_date(u.rtime, 'MM/DD/YYYY HH24:MI:SS'), 'YYYY-MM-DD HH24:MI:SS') || '|' ||
       round(u.tablespace_size * bs.block_size / 1024 / 1024 / 1024, 2) || '|' ||
       round(u.tablespace_usedsize * bs.block_size / 1024 / 1024 / 1024, 2) || '|' ||
       round(u.tablespace_usedsize / nullif(u.tablespace_maxsize, 0) * 100, 2)
FROM dba_hist_tbspc_space_usage u
JOIN v$tablespace ts ON ts.ts# = u.tablespace_id
CROSS JOIN (
  SELECT to_number(value) block_size FROM v$parameter WHERE name = 'db_block_size'
) bs
WHERE to_date(u.rtime, 'MM/DD/YYYY HH24:MI:SS') >= SYSDATE - &&DAYS_BACK
ORDER BY ts.name, u.rtime;
exit
"""


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_db_workload_output(text: str) -> list[dict[str, str]]:
    return _parse_pipe_rows(
        text, WORKLOAD_SQL_COLUMNS, len(WORKLOAD_SQL_COLUMNS), "DB workload"
    )


def parse_db_tablespace_growth_output(text: str) -> list[dict[str, str]]:
    return _parse_pipe_rows(
        text,
        TABLESPACE_GROWTH_SQL_COLUMNS,
        len(TABLESPACE_GROWTH_SQL_COLUMNS),
        "DB tablespace growth",
    )


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DBWorkloadCollector:
    """Collect AWR workload intensity and tablespace growth per local DB."""

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
        use_awr: bool = True,
        days_back: int = 7,
        timeout_seconds: int = 120,
        collect_workload: bool = True,
        collect_tablespace_growth: bool = True,
        sql_executor=None,
    ) -> tuple[list[DBWorkloadRecord], list[DBTablespaceGrowthRecord]]:
        if not enabled or not use_awr:
            return [], []

        workload_records: list[DBWorkloadRecord] = []
        tablespace_records: list[DBTablespaceGrowthRecord] = []
        now = _utc_now()

        for detail in _local_success_db_details(db_inventory.db_resource_details):
            db_unique_name = str(
                detail.get("db_unique_name") or detail.get("DB_NAME") or ""
            )
            oracle_home = str(detail.get("oracle_home") or "")
            oracle_sid = str(detail.get("oracle_sid") or "")
            open_mode = str(
                detail.get("OPEN_MODE") or detail.get("open_mode") or ""
            ).upper()
            # AWR queries need the DB open read-write/read-only.
            if open_mode and open_mode not in {"READ WRITE", "READ ONLY"}:
                continue
            if collect_workload:
                workload_records.extend(
                    self._collect_workload(
                        db_inventory, host, db_unique_name, oracle_home,
                        oracle_sid, days_back, timeout_seconds, now, sql_executor,
                    )
                )
            if collect_tablespace_growth:
                tablespace_records.extend(
                    self._collect_tablespace_growth(
                        db_inventory, host, db_unique_name, oracle_home,
                        oracle_sid, days_back, timeout_seconds, now, sql_executor,
                    )
                )
        return workload_records, tablespace_records

    def _collect_workload(
        self, inv, host, db_unique_name, oracle_home, oracle_sid,
        days_back, timeout_seconds, collected_at, sql_executor,
    ) -> list[DBWorkloadRecord]:
        result = _execute_sql(
            self.runner, host, oracle_home, oracle_sid,
            build_db_workload_sql(days_back), timeout_seconds, sql_executor, "workload",
        )
        if not result.ok:
            return [
                self._failed_workload(
                    inv, db_unique_name, oracle_home, oracle_sid, collected_at,
                    _sql_failure_error(result, inv.host),
                    _db_perf_error_category(
                        result.stdout, result.stderr, getattr(result, "error", "")
                    ),
                    result,
                )
            ]
        try:
            rows = parse_db_workload_output(result.stdout)
        except ValueError as exc:
            return [
                self._failed_workload(
                    inv, db_unique_name, oracle_home, oracle_sid, collected_at,
                    str(exc), "PARSE_ERROR", result,
                )
            ]
        return [
            DBWorkloadRecord(
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

    def _collect_tablespace_growth(
        self, inv, host, db_unique_name, oracle_home, oracle_sid,
        days_back, timeout_seconds, collected_at, sql_executor,
    ) -> list[DBTablespaceGrowthRecord]:
        result = _execute_sql(
            self.runner, host, oracle_home, oracle_sid,
            build_db_tablespace_growth_sql(days_back), timeout_seconds,
            sql_executor, "tablespace_growth",
        )
        if not result.ok:
            return [
                self._failed_tablespace(
                    inv, db_unique_name, oracle_home, oracle_sid, collected_at,
                    _sql_failure_error(result, inv.host),
                    _db_perf_error_category(
                        result.stdout, result.stderr, getattr(result, "error", "")
                    ),
                    result,
                )
            ]
        try:
            rows = parse_db_tablespace_growth_output(result.stdout)
        except ValueError as exc:
            return [
                self._failed_tablespace(
                    inv, db_unique_name, oracle_home, oracle_sid, collected_at,
                    str(exc), "PARSE_ERROR", result,
                )
            ]
        return [
            DBTablespaceGrowthRecord(
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

    def _failed_workload(
        self, inv, db_unique_name, oracle_home, oracle_sid, collected_at,
        error, category, result=None,
    ) -> DBWorkloadRecord:
        return DBWorkloadRecord(
            Cluster=inv.cluster,
            HOST_NAME=inv.host,
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

    def _failed_tablespace(
        self, inv, db_unique_name, oracle_home, oracle_sid, collected_at,
        error, category, result=None,
    ) -> DBTablespaceGrowthRecord:
        return DBTablespaceGrowthRecord(
            Cluster=inv.cluster,
            HOST_NAME=inv.host,
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
