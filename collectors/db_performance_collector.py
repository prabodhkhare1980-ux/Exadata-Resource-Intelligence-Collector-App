"""AWR-backed DB CPU, IOPS, and memory history collector.

This collector queries DBA_HIST_* AWR views and therefore requires Oracle
Diagnostics Pack licensing for every database where it is enabled.
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

from collectors.db_inventory_collector import DBInventoryRecord, _sql_failure_error
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig

AWR_ERROR_CATEGORY = "AWR_UNAVAILABLE_OR_PRIVILEGE"

DB_PERFORMANCE_COLUMNS = [
    "Cluster",
    "HOST_NAME",
    "DB_NAME",
    "INSTANCE_NAME",
    "END_TIME",
    "READ_IOPS_AVG",
    "WRITE_IOPS_AVG",
    "TOTAL_IOPS_AVG",
    "READ_IOPS_MAX",
    "WRITE_IOPS_MAX",
    "TOTAL_IOPS_MAX",
    "READ_MBPS_AVG",
    "WRITE_MBPS_AVG",
    "TOTAL_MBPS_AVG",
    "READ_MBPS_MAX",
    "WRITE_MBPS_MAX",
    "TOTAL_MBPS_MAX",
    "CPU_USAGE_PER_SEC_AVG",
    "CPU_USAGE_PER_SEC_MAX",
    "HOST_CPU_UTIL_PCT_AVG",
    "HOST_CPU_UTIL_PCT_MAX",
    "Collected_At",
    "db_unique_name",
    "source_host",
    "source_address",
    "source_oracle_sid",
    "collection_status",
    "collection_error",
    "error_category",
    "size_source",
    "duplicate_count",
]

DB_PERFORMANCE_SQL_COLUMNS = [
    "DB_NAME",
    "INSTANCE_NAME",
    "HOST_NAME",
    "END_TIME",
    *DB_PERFORMANCE_COLUMNS[5:21],
]

SGA_COMPONENT_COLUMNS = [
    "SGA_FIXED_GB",
    "SGA_REDO_GB",
    "SGA_BUFFER_CACHE_GB",
    "SGA_SHARED_POOL_GB",
    "SGA_LARGE_POOL_GB",
    "SGA_JAVA_POOL_GB",
    "SGA_STREAMS_POOL_GB",
    "SGA_SHARED_IO_POOL_GB",
    "SGA_INMEMORY_AREA_GB",
    "SGA_RESULT_CACHE_GB",
    "SGA_OTHER_GB",
]

DB_MEMORY_COLUMNS = [
    "Cluster",
    "HOST_NAME",
    "DB_NAME",
    "INSTANCE_NAME",
    "END_TIME",
    "SGA_TARGET_GB",
    "SGA_MAX_SIZE_GB",
    "SGA_USED_GB",
    *SGA_COMPONENT_COLUMNS,
    "PGA_AGGREGATE_TARGET_GB",
    "PGA_AGGREGATE_LIMIT_GB",
    "PGA_ALLOCATED_GB",
    "PGA_USED_GB",
    "PGA_FREEABLE_GB",
    "PGA_MAX_ALLOCATED_GB",
    "Collected_At",
    "db_unique_name",
    "source_host",
    "source_address",
    "source_oracle_sid",
    "collection_status",
    "collection_error",
    "error_category",
    "size_source",
    "duplicate_count",
    "collection_scope",
    "collection_source_selected",
    "collection_source_reason",
]

DB_MEMORY_SQL_COLUMNS = [
    "DB_NAME",
    "INSTANCE_NAME",
    "HOST_NAME",
    "END_TIME",
    *DB_MEMORY_COLUMNS[5:25],
]
DB_MEMORY_LEGACY_SQL_COLUMNS = [
    "DB_NAME",
    "INSTANCE_NAME",
    "HOST_NAME",
    "END_TIME",
    "SGA_TARGET_GB",
    "SGA_MAX_SIZE_GB",
    "SGA_USED_GB",
    "PGA_AGGREGATE_TARGET_GB",
    "PGA_AGGREGATE_LIMIT_GB",
    "PGA_ALLOCATED_GB",
    "PGA_USED_GB",
    "PGA_FREEABLE_GB",
    "PGA_MAX_ALLOCATED_GB",
]


@dataclass
class DBPerformanceRecord:
    Cluster: str
    HOST_NAME: str
    DB_NAME: str = ""
    INSTANCE_NAME: str = ""
    END_TIME: str = ""
    READ_IOPS_AVG: str = ""
    WRITE_IOPS_AVG: str = ""
    TOTAL_IOPS_AVG: str = ""
    READ_IOPS_MAX: str = ""
    WRITE_IOPS_MAX: str = ""
    TOTAL_IOPS_MAX: str = ""
    READ_MBPS_AVG: str = ""
    WRITE_MBPS_AVG: str = ""
    TOTAL_MBPS_AVG: str = ""
    READ_MBPS_MAX: str = ""
    WRITE_MBPS_MAX: str = ""
    TOTAL_MBPS_MAX: str = ""
    CPU_USAGE_PER_SEC_AVG: str = ""
    CPU_USAGE_PER_SEC_MAX: str = ""
    HOST_CPU_UTIL_PCT_AVG: str = ""
    HOST_CPU_UTIL_PCT_MAX: str = ""
    Collected_At: str = ""
    db_unique_name: str = ""
    source_host: str = ""
    source_address: str = ""
    source_oracle_sid: str = ""
    collection_status: str = "success"
    collection_error: str = ""
    error_category: str = ""
    size_source: str = "AWR"
    duplicate_count: int = 1
    oracle_home: str = ""
    host: str = ""
    address: str = ""
    oracle_sid: str = ""
    sql_returncode: int | str = ""
    sql_stdout: str = ""
    sql_stderr: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return {column: getattr(self, column) for column in DB_PERFORMANCE_COLUMNS}

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class DBMemoryHistoryRecord:
    Cluster: str
    HOST_NAME: str
    DB_NAME: str = ""
    INSTANCE_NAME: str = ""
    END_TIME: str = ""
    SGA_TARGET_GB: str = ""
    SGA_MAX_SIZE_GB: str = ""
    SGA_USED_GB: str = ""
    SGA_FIXED_GB: str = ""
    SGA_REDO_GB: str = ""
    SGA_BUFFER_CACHE_GB: str = ""
    SGA_SHARED_POOL_GB: str = ""
    SGA_LARGE_POOL_GB: str = ""
    SGA_JAVA_POOL_GB: str = ""
    SGA_STREAMS_POOL_GB: str = ""
    SGA_SHARED_IO_POOL_GB: str = ""
    SGA_INMEMORY_AREA_GB: str = ""
    SGA_RESULT_CACHE_GB: str = ""
    SGA_OTHER_GB: str = ""
    PGA_AGGREGATE_TARGET_GB: str = ""
    PGA_AGGREGATE_LIMIT_GB: str = ""
    PGA_ALLOCATED_GB: str = ""
    PGA_USED_GB: str = ""
    PGA_FREEABLE_GB: str = ""
    PGA_MAX_ALLOCATED_GB: str = ""
    Collected_At: str = ""
    db_unique_name: str = ""
    source_host: str = ""
    source_address: str = ""
    source_oracle_sid: str = ""
    collection_status: str = "success"
    collection_error: str = ""
    error_category: str = ""
    size_source: str = "AWR"
    duplicate_count: int = 1
    collection_scope: str = ""
    collection_source_selected: bool | str = ""
    collection_source_reason: str = ""
    oracle_home: str = ""
    host: str = ""
    address: str = ""
    oracle_sid: str = ""
    sql_returncode: int | str = ""
    sql_stdout: str = ""
    sql_stderr: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return {column: getattr(self, column) for column in DB_MEMORY_COLUMNS}

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


class DBPerformanceCollector:
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
        timeout_seconds: int = 90,
        collect_cpu_iops: bool = True,
        collect_memory_history: bool = True,
        sql_executor=None,
    ) -> tuple[list[DBPerformanceRecord], list[DBMemoryHistoryRecord]]:
        if not enabled:
            return [], []
        if not use_awr:
            now = _utc_now()
            perf = [
                self._failed_perf(
                    db_inventory, "", "", "", now, "use_awr_false", "AWR_DISABLED"
                )
            ]
            mem = [
                self._failed_mem(
                    db_inventory, "", "", "", now, "use_awr_false", "AWR_DISABLED"
                )
            ]
            return (perf if collect_cpu_iops else []), (
                mem if collect_memory_history else []
            )

        perf_records: list[DBPerformanceRecord] = []
        memory_records: list[DBMemoryHistoryRecord] = []
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
            if open_mode and open_mode not in {"READ WRITE", "READ ONLY"}:
                if collect_cpu_iops:
                    perf_records.append(
                        self._failed_perf(
                            db_inventory,
                            db_unique_name,
                            oracle_home,
                            oracle_sid,
                            now,
                            "db_not_open",
                            "DB_NOT_OPEN",
                            status="skipped",
                        )
                    )
                if collect_memory_history:
                    memory_records.append(
                        self._failed_mem(
                            db_inventory,
                            db_unique_name,
                            oracle_home,
                            oracle_sid,
                            now,
                            "db_not_open",
                            "DB_NOT_OPEN",
                            status="skipped",
                        )
                    )
                continue
            if collect_cpu_iops:
                perf_records.extend(
                    self._collect_performance(
                        db_inventory,
                        host,
                        db_unique_name,
                        oracle_home,
                        oracle_sid,
                        days_back,
                        timeout_seconds,
                        now,
                        sql_executor,
                    )
                )
            if collect_memory_history:
                memory_records.extend(
                    self._collect_memory(
                        db_inventory,
                        host,
                        db_unique_name,
                        oracle_home,
                        oracle_sid,
                        days_back,
                        timeout_seconds,
                        now,
                        sql_executor,
                    )
                )
        return perf_records, memory_records

    def collect_cluster_memory_history(
        self,
        db_inventories: Iterable[DBInventoryRecord],
        hosts_by_name: dict[str, "HostConfig"],
        *,
        enabled: bool = True,
        use_awr: bool = True,
        days_back: int = 7,
        timeout_seconds: int = 90,
        sql_executor=None,
    ) -> list[DBMemoryHistoryRecord]:
        """Collect DB memory history once per db_unique_name within a cluster.

        The first running instance discovered is selected as the primary collection
        source. If it fails, subsequent running instances for the same
        db_unique_name are retried until one succeeds or all candidates fail.
        """

        if not enabled:
            return []

        now = _utc_now()
        if not use_awr:
            records = [
                self._mark_memory_collection_source(
                    self._failed_mem(
                        inv, "", "", "", now, "use_awr_false", "AWR_DISABLED"
                    ),
                    duplicate_count=1,
                    selected=True,
                    reason="primary_selected",
                )
                for inv in db_inventories
            ]
            self.logger.info(
                "DB memory history: db_unique_names_total=%s collected=%s skipped_duplicates=%s failed=%s",
                len(records),
                0,
                0,
                len(records),
            )
            return records

        grouped: dict[
            tuple[str, str], list[tuple[DBInventoryRecord, dict[str, object]]]
        ] = {}
        for inv in db_inventories:
            for detail in _local_success_db_details(inv.db_resource_details):
                db_unique_name = str(
                    detail.get("db_unique_name") or detail.get("DB_NAME") or ""
                ).strip()
                if not db_unique_name:
                    continue
                open_mode = str(
                    detail.get("OPEN_MODE") or detail.get("open_mode") or ""
                ).upper()
                if open_mode and open_mode not in {"READ WRITE", "READ ONLY"}:
                    continue
                grouped.setdefault((inv.cluster, db_unique_name), []).append(
                    (inv, detail)
                )

        records: list[DBMemoryHistoryRecord] = []
        collected = 0
        failed = 0
        skipped_duplicates = 0
        for (_cluster, db_unique_name), candidates in grouped.items():
            duplicate_count = len(candidates)
            selected_success = False
            attempted_indexes: set[int] = set()
            for index, (inv, detail) in enumerate(candidates):
                attempted_indexes.add(index)
                host = hosts_by_name.get(inv.host)
                if host is None:
                    failure = self._failed_mem(
                        inv,
                        db_unique_name,
                        str(detail.get("oracle_home") or ""),
                        str(detail.get("oracle_sid") or ""),
                        now,
                        f"host_config_not_found_for_{inv.host}",
                        "CONFIG_ERROR",
                    )
                    records.append(
                        self._mark_memory_collection_source(
                            failure,
                            duplicate_count=duplicate_count,
                            selected=True,
                            reason=(
                                "primary_selected" if index == 0 else "retry_selected"
                            ),
                        )
                    )
                    continue

                attempt_records = self._collect_memory(
                    inv,
                    host,
                    db_unique_name,
                    str(detail.get("oracle_home") or ""),
                    str(detail.get("oracle_sid") or ""),
                    days_back,
                    timeout_seconds,
                    now,
                    sql_executor,
                )
                reason = "primary_selected" if index == 0 else "retry_selected"
                for record in attempt_records:
                    records.append(
                        self._mark_memory_collection_source(
                            record,
                            duplicate_count=duplicate_count,
                            selected=True,
                            reason=reason,
                        )
                    )
                if attempt_records and all(
                    record.collection_status == "success" for record in attempt_records
                ):
                    selected_success = True
                    collected += 1
                    break

            if not selected_success:
                failed += 1

            for index, (inv, detail) in enumerate(candidates):
                if index in attempted_indexes:
                    continue
                skipped_duplicates += 1
                records.append(
                    self._mark_memory_collection_source(
                        self._failed_mem(
                            inv,
                            db_unique_name,
                            str(detail.get("oracle_home") or ""),
                            str(detail.get("oracle_sid") or ""),
                            now,
                            "duplicate db_unique_name collected from selected cluster source",
                            "SKIPPED_DUPLICATE",
                            status="skipped",
                        ),
                        duplicate_count=duplicate_count,
                        selected=False,
                        reason="skipped_duplicate",
                    )
                )

        self.logger.info(
            "DB memory history: db_unique_names_total=%s collected=%s skipped_duplicates=%s failed=%s",
            len(grouped),
            collected,
            skipped_duplicates,
            failed,
        )
        return records

    def _mark_memory_collection_source(
        self,
        record: DBMemoryHistoryRecord,
        *,
        duplicate_count: int,
        selected: bool,
        reason: str,
    ) -> DBMemoryHistoryRecord:
        record.collection_scope = "cluster_db_unique_name"
        record.collection_source_selected = selected
        record.collection_source_reason = reason
        record.duplicate_count = duplicate_count
        return record

    def _collect_performance(
        self,
        inv,
        host,
        db_unique_name,
        oracle_home,
        oracle_sid,
        days_back,
        timeout_seconds,
        collected_at,
        sql_executor,
    ) -> list[DBPerformanceRecord]:
        result = _execute_sql(
            self.runner,
            host,
            oracle_home,
            oracle_sid,
            _build_db_performance_sql(days_back),
            timeout_seconds,
            sql_executor,
            "performance",
        )
        if not result.ok:
            return [
                self._failed_perf(
                    inv,
                    db_unique_name,
                    oracle_home,
                    oracle_sid,
                    collected_at,
                    _sql_failure_error(result, inv.host),
                    _db_perf_error_category(
                        result.stdout, result.stderr, getattr(result, "error", "")
                    ),
                    result,
                )
            ]
        try:
            return [
                DBPerformanceRecord(
                    Cluster=inv.cluster,
                    Collected_At=collected_at,
                    source_host=inv.host,
                    source_address=inv.address,
                    source_oracle_sid=oracle_sid,
                    db_unique_name=db_unique_name,
                    oracle_home=oracle_home,
                    host=inv.host,
                    address=inv.address,
                    oracle_sid=oracle_sid,
                    **row,
                )
                for row in parse_db_performance_output(result.stdout)
            ]
        except ValueError as exc:
            return [
                self._failed_perf(
                    inv,
                    db_unique_name,
                    oracle_home,
                    oracle_sid,
                    collected_at,
                    str(exc),
                    "PARSE_ERROR",
                    result,
                )
            ]

    def _collect_memory(
        self,
        inv,
        host,
        db_unique_name,
        oracle_home,
        oracle_sid,
        days_back,
        timeout_seconds,
        collected_at,
        sql_executor,
    ) -> list[DBMemoryHistoryRecord]:
        result = _execute_sql(
            self.runner,
            host,
            oracle_home,
            oracle_sid,
            _build_db_memory_sql(days_back),
            timeout_seconds,
            sql_executor,
            "memory",
        )
        if not result.ok:
            return [
                self._failed_mem(
                    inv,
                    db_unique_name,
                    oracle_home,
                    oracle_sid,
                    collected_at,
                    _sql_failure_error(result, inv.host),
                    _db_perf_error_category(
                        result.stdout, result.stderr, getattr(result, "error", "")
                    ),
                    result,
                )
            ]
        try:
            return [
                DBMemoryHistoryRecord(
                    Cluster=inv.cluster,
                    Collected_At=collected_at,
                    source_host=inv.host,
                    source_address=inv.address,
                    source_oracle_sid=oracle_sid,
                    db_unique_name=db_unique_name,
                    oracle_home=oracle_home,
                    host=inv.host,
                    address=inv.address,
                    oracle_sid=oracle_sid,
                    **row,
                )
                for row in parse_db_memory_output(result.stdout)
            ]
        except ValueError as exc:
            return [
                self._failed_mem(
                    inv,
                    db_unique_name,
                    oracle_home,
                    oracle_sid,
                    collected_at,
                    str(exc),
                    "PARSE_ERROR",
                    result,
                )
            ]

    def _failed_perf(
        self,
        inv,
        db_unique_name,
        oracle_home,
        oracle_sid,
        collected_at,
        error,
        category,
        result=None,
        status="failed",
    ) -> DBPerformanceRecord:
        return DBPerformanceRecord(
            Cluster=inv.cluster,
            HOST_NAME=inv.host,
            Collected_At=collected_at,
            source_host=inv.host,
            source_address=inv.address,
            source_oracle_sid=oracle_sid,
            host=inv.host,
            address=inv.address,
            db_unique_name=db_unique_name,
            oracle_home=oracle_home,
            oracle_sid=oracle_sid,
            collection_status=status,
            collection_error=error,
            error_category=category,
            sql_returncode=getattr(result, "returncode", ""),
            sql_stdout=getattr(result, "stdout", "").strip() if result else "",
            sql_stderr=getattr(result, "stderr", "").strip() if result else "",
        )

    def _failed_mem(
        self,
        inv,
        db_unique_name,
        oracle_home,
        oracle_sid,
        collected_at,
        error,
        category,
        result=None,
        status="failed",
    ) -> DBMemoryHistoryRecord:
        return DBMemoryHistoryRecord(
            Cluster=inv.cluster,
            HOST_NAME=inv.host,
            Collected_At=collected_at,
            source_host=inv.host,
            source_address=inv.address,
            source_oracle_sid=oracle_sid,
            host=inv.host,
            address=inv.address,
            db_unique_name=db_unique_name,
            oracle_home=oracle_home,
            oracle_sid=oracle_sid,
            collection_status=status,
            collection_error=error,
            error_category=category,
            sql_returncode=getattr(result, "returncode", ""),
            sql_stdout=getattr(result, "stdout", "").strip() if result else "",
            sql_stderr=getattr(result, "stderr", "").strip() if result else "",
        )


def _local_success_db_details(
    details: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        detail
        for detail in details
        if str(detail.get("collection_status") or "").lower() == "success"
        and str(detail.get("oracle_sid") or "").strip()
        and str(detail.get("oracle_home") or "").strip()
    ]


def parse_db_performance_output(text: str) -> list[dict[str, str]]:
    return _parse_pipe_rows(text, DB_PERFORMANCE_SQL_COLUMNS, 20, "DB performance")


def parse_db_memory_output(text: str) -> list[dict[str, str]]:
    return _parse_pipe_rows_with_legacy(
        text,
        DB_MEMORY_SQL_COLUMNS,
        legacy_columns=DB_MEMORY_LEGACY_SQL_COLUMNS,
        label="DB memory history",
    )


SQL_ECHO_PREFIXES = (
    "whenever",
    "set",
    "select",
    "with",
    "from",
    "pivot",
    "order by",
    "exit",
)


def _parse_pipe_rows_with_legacy(
    text: str, columns: list[str], legacy_columns: list[str], label: str
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    valid_lengths = {len(columns): columns, len(legacy_columns): legacy_columns}
    valid_delimiters = {length - 1 for length in valid_lengths}
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        lower_line = line.lower()
        if (
            not line
            or lower_line.startswith("sql>")
            or line.startswith("-")
            or lower_line.startswith(SQL_ECHO_PREFIXES)
        ):
            continue
        if line.count("|") not in valid_delimiters:
            continue
        parts = [part.strip() for part in line.split("|")]
        row_columns = valid_lengths.get(len(parts))
        if row_columns is None:
            continue
        row = dict(zip(row_columns, parts, strict=True))
        for column in columns:
            row.setdefault(column, "")
        rows.append(row)
    if not rows:
        expected = "/".join(str(length) for length in sorted(valid_lengths))
        raise ValueError(f"Expected pipe-delimited {label} rows with {expected} fields")
    return rows


def _parse_pipe_rows(
    text: str, columns: list[str], expected: int, label: str
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    expected_delimiters = expected - 1
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        lower_line = line.lower()
        if (
            not line
            or lower_line.startswith("sql>")
            or line.startswith("-")
            or lower_line.startswith(SQL_ECHO_PREFIXES)
        ):
            continue
        if line.count("|") != expected_delimiters:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != expected:
            continue
        rows.append(dict(zip(columns, parts, strict=True)))
    if not rows:
        raise ValueError(
            f"Expected {expected_delimiters} pipe delimiters / {expected} {label} fields"
        )
    return rows


def _build_sqlplus_command(oracle_home: str, sid: str, timeout_seconds: int) -> str:
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
            f"{int(timeout_seconds)}s",
            "sqlplus",
            "-s",
            "/",
            "as",
            "sysdba",
        ]
    )


def _execute_sql(
    runner, host, oracle_home, sid, sql, timeout_seconds, sql_executor, sql_kind: str
):
    if sql_executor is not None:
        return sql_executor(oracle_home, sid, sql, sql_kind)
    if runner is None:
        raise ValueError("runner is required when sql_executor is not supplied")
    command = _build_sqlplus_command(oracle_home, sid, timeout_seconds)
    ssh_command = [
        *runner._build_ssh_command(
            host, allocate_tty=getattr(host, "force_tty", False)
        ),
        command,
    ]
    return runner._run(ssh_command, host, sql)


def _db_perf_error_category(stdout: str = "", stderr: str = "", error: str = "") -> str:
    upper = f"{stdout}\n{stderr}\n{error}".upper()
    if "ORA-01219" in upper or "DATABASE NOT OPEN" in upper or "DB_NOT_OPEN" in upper:
        return "DB_NOT_OPEN"
    if "ORA-00904" in upper:
        return "SQL_BUG"
    if "ORA-01555" in upper or "TIMED OUT" in upper or "TIMEOUT" in upper:
        return "SQL_RUNTIME"
    if "ORA-00942" in upper or "ORA-01031" in upper:
        return AWR_ERROR_CATEGORY
    if (
        "AWR DISABLED" in upper
        or "AWR UNAVAILABLE" in upper
        or "MISSING DBA_HIST" in upper
    ):
        return AWR_ERROR_CATEGORY
    if "DBA_HIST" in upper and "ORA-00904" not in upper:
        return AWR_ERROR_CATEGORY
    if "ORA-" in upper:
        return "ORACLE_ERROR"
    if "SP2-" in upper:
        return "SQLPLUS_ERROR"
    return "UNKNOWN"


def _build_db_performance_sql(days_back: int) -> str:
    days = max(int(days_back), 1)
    return f"""
WHENEVER OSERROR EXIT 9;
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
define DAYS_BACK={days}

WITH data1 AS (
  SELECT b.instance_name, b.host_name, a.end_time, a.metric_name, a.average, a.maxval
  FROM dba_hist_sysmetric_summary a
  JOIN gv$instance b ON a.instance_number = b.instance_number
  WHERE a.metric_name IN (
      'CPU Usage Per Sec', 'Host CPU Utilization (%)',
      'Physical Read Total IO Requests Per Sec', 'Physical Write Total IO Requests Per Sec',
      'Physical Read Total Bytes Per Sec', 'Physical Write Total Bytes Per Sec'
  )
  AND a.end_time >= SYSDATE - &&DAYS_BACK
),
data2 AS (SELECT trim(name) database_name FROM v$database)
SELECT database_name || '|' || instance_name || '|' || host_name || '|' || to_char(end_time,'YYYY-MM-DD HH24:MI:SS') || '|' ||
    nvl(round(read_iops_avg,0),0) || '|' || nvl(round(write_iops_avg,0),0) || '|' || nvl(round(read_iops_avg + write_iops_avg,0),0) || '|' ||
    nvl(round(read_iops_max,0),0) || '|' || nvl(round(write_iops_max,0),0) || '|' || nvl(round(read_iops_max + write_iops_max,0),0) || '|' ||
    nvl(round(read_thrpt_avg/1024/1024,0),0) || '|' || nvl(round(write_thrpt_avg/1024/1024,0),0) || '|' || nvl(round((read_thrpt_avg + write_thrpt_avg)/1024/1024,0),0) || '|' ||
    nvl(round(read_thrpt_max/1024/1024,0),0) || '|' || nvl(round(write_thrpt_max/1024/1024,0),0) || '|' || nvl(round((read_thrpt_max + write_thrpt_max)/1024/1024,0),0) || '|' ||
    nvl(round(cpu_usage_avg,2),0) || '|' || nvl(round(cpu_usage_max,2),0) || '|' || nvl(round(host_cpu_avg,2),0) || '|' || nvl(round(host_cpu_max,2),0)
FROM (SELECT * FROM data2 CROSS JOIN data1)
PIVOT (
  max(average) AS avg, max(maxval) AS max
  FOR metric_name IN (
    'Physical Write Total IO Requests Per Sec' AS write_iops,
    'Physical Read Total IO Requests Per Sec' AS read_iops,
    'Physical Read Total Bytes Per Sec' AS read_thrpt,
    'Physical Write Total Bytes Per Sec' AS write_thrpt,
    'CPU Usage Per Sec' AS cpu_usage,
    'Host CPU Utilization (%)' AS host_cpu
  )
)
ORDER BY end_time;
exit
""".replace("\r\n", "\n").replace("\r", "\n").lstrip()


def _build_db_memory_sql(days_back: int) -> str:
    days = max(int(days_back), 1)
    return f"""
WHENEVER OSERROR EXIT 9;
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
define DAYS_BACK={days}

WITH snaps AS (
  SELECT snap_id,
         dbid,
         instance_number,
         startup_time,
         begin_interval_time,
         end_interval_time end_time
  FROM dba_hist_snapshot
  WHERE end_interval_time >= SYSDATE - &&DAYS_BACK
),
db AS (
  SELECT trim(name) database_name FROM v$database
),
inst AS (
  SELECT dbid,
         instance_number,
         startup_time,
         instance_name,
         host_name
  FROM dba_hist_database_instance
),
params AS (
  SELECT snap_id,
         dbid,
         instance_number,
         max(CASE WHEN parameter_name='sga_target' THEN value END) sga_target,
         max(CASE WHEN parameter_name='sga_max_size' THEN value END) sga_max_size,
         max(CASE WHEN parameter_name='pga_aggregate_target' THEN value END) pga_aggregate_target,
         max(CASE WHEN parameter_name='pga_aggregate_limit' THEN value END) pga_aggregate_limit
  FROM dba_hist_parameter
  WHERE parameter_name IN (
    'sga_target',
    'sga_max_size',
    'pga_aggregate_target',
    'pga_aggregate_limit'
  )
  GROUP BY snap_id, dbid, instance_number
),
sga AS (
  SELECT snap_id,
         dbid,
         instance_number,
         sum(bytes) sga_used,
         sum(case when lower(name) like 'fixed_sga%' then bytes else 0 end) sga_fixed,
         sum(case when lower(name) like 'log_buffer%' then bytes else 0 end) sga_redo,
         sum(case
               when lower(pool) = 'buffer cache'
                 or lower(name) like '%buffer_cache%'
                 or lower(name) like 'db block buffers%'
               then bytes else 0
             end) sga_buffer_cache,
         sum(case when lower(pool) = 'shared pool' then bytes else 0 end) sga_shared_pool,
         sum(case when lower(pool) = 'large pool' then bytes else 0 end) sga_large_pool,
         sum(case when lower(pool) = 'java pool' then bytes else 0 end) sga_java_pool,
         sum(case when lower(pool) = 'streams pool' then bytes else 0 end) sga_streams_pool,
         sum(case when lower(pool) = 'shared io pool' then bytes else 0 end) sga_shared_io_pool,
         sum(case when lower(pool) = 'inmemory area' then bytes else 0 end) sga_inmemory_area,
         sum(case when lower(name) like '%result cache%' then bytes else 0 end) sga_result_cache
  FROM dba_hist_sgastat
  GROUP BY snap_id, dbid, instance_number
),
pga AS (
  SELECT snap_id,
         dbid,
         instance_number,
         max(CASE WHEN name='total PGA allocated' THEN value END) pga_allocated,
         max(CASE WHEN name='total PGA inuse' THEN value END) pga_used,
         max(CASE WHEN name='total freeable PGA memory' THEN value END) pga_freeable,
         max(CASE WHEN name='maximum PGA allocated' THEN value END) pga_max_allocated
  FROM dba_hist_pgastat
  WHERE name IN (
    'total PGA allocated',
    'total PGA inuse',
    'total freeable PGA memory',
    'maximum PGA allocated'
  )
  GROUP BY snap_id, dbid, instance_number
)
SELECT db.database_name || '|' ||
       nvl(inst.instance_name, 'UNKNOWN') || '|' ||
       nvl(inst.host_name, '') || '|' ||
       to_char(snaps.end_time,'YYYY-MM-DD HH24:MI:SS') || '|' ||
       nvl(round(params.sga_target/1024/1024/1024,2),0) || '|' ||
       nvl(round(params.sga_max_size/1024/1024/1024,2),0) || '|' ||
       nvl(round(sga.sga_used/1024/1024/1024,2),0) || '|' ||
       round(nvl(sga.sga_fixed,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_redo,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_buffer_cache,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_shared_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_large_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_java_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_streams_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_shared_io_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_inmemory_area,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_result_cache,0)/1024/1024/1024,2) || '|' ||
       round(greatest(
         nvl(sga.sga_used,0)
         - nvl(sga.sga_fixed,0)
         - nvl(sga.sga_redo,0)
         - nvl(sga.sga_buffer_cache,0)
         - nvl(sga.sga_shared_pool,0)
         - nvl(sga.sga_large_pool,0)
         - nvl(sga.sga_java_pool,0)
         - nvl(sga.sga_streams_pool,0)
         - nvl(sga.sga_shared_io_pool,0)
         - nvl(sga.sga_inmemory_area,0)
         - nvl(sga.sga_result_cache,0), 0
       )/1024/1024/1024,2) || '|' ||
       nvl(round(params.pga_aggregate_target/1024/1024/1024,2),0) || '|' ||
       nvl(round(params.pga_aggregate_limit/1024/1024/1024,2),0) || '|' ||
       nvl(round(pga.pga_allocated/1024/1024/1024,2),0) || '|' ||
       nvl(round(pga.pga_used/1024/1024/1024,2),0) || '|' ||
       nvl(round(pga.pga_freeable/1024/1024/1024,2),0) || '|' ||
       nvl(round(pga.pga_max_allocated/1024/1024/1024,2),0)
FROM snaps
CROSS JOIN db
LEFT JOIN inst
  ON inst.dbid = snaps.dbid
 AND inst.instance_number = snaps.instance_number
 AND inst.startup_time = snaps.startup_time
LEFT JOIN params
  ON params.snap_id = snaps.snap_id
 AND params.dbid = snaps.dbid
 AND params.instance_number = snaps.instance_number
LEFT JOIN sga
  ON sga.snap_id = snaps.snap_id
 AND sga.dbid = snaps.dbid
 AND sga.instance_number = snaps.instance_number
LEFT JOIN pga
  ON pga.snap_id = snaps.snap_id
 AND pga.dbid = snaps.dbid
 AND pga.instance_number = snaps.instance_number
ORDER BY snaps.end_time, inst.instance_name;
exit
""".replace("\r\n", "\n").replace("\r", "\n").lstrip()


def _build_db_memory_current_sql() -> str:
    return """
WHENEVER OSERROR EXIT 9;
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

WITH db AS (
  SELECT trim(name) database_name FROM v$database
),
inst AS (
  SELECT inst_id,
         instance_name,
         host_name
  FROM gv$instance
),
params AS (
  SELECT inst_id,
         max(CASE WHEN name='sga_target' THEN value END) sga_target,
         max(CASE WHEN name='sga_max_size' THEN value END) sga_max_size,
         max(CASE WHEN name='pga_aggregate_target' THEN value END) pga_aggregate_target,
         max(CASE WHEN name='pga_aggregate_limit' THEN value END) pga_aggregate_limit
  FROM gv$parameter
  WHERE name IN ('sga_target', 'sga_max_size', 'pga_aggregate_target', 'pga_aggregate_limit')
  GROUP BY inst_id
),
sga AS (
  SELECT inst_id,
         sum(bytes) sga_used,
         sum(case when lower(name) like 'fixed_sga%' then bytes else 0 end) sga_fixed,
         sum(case when lower(name) like 'log_buffer%' then bytes else 0 end) sga_redo,
         sum(case
               when lower(pool) = 'buffer cache'
                 or lower(name) like '%buffer_cache%'
                 or lower(name) like 'db block buffers%'
               then bytes else 0
             end) sga_buffer_cache,
         sum(case when lower(pool) = 'shared pool' then bytes else 0 end) sga_shared_pool,
         sum(case when lower(pool) = 'large pool' then bytes else 0 end) sga_large_pool,
         sum(case when lower(pool) = 'java pool' then bytes else 0 end) sga_java_pool,
         sum(case when lower(pool) = 'streams pool' then bytes else 0 end) sga_streams_pool,
         sum(case when lower(pool) = 'shared io pool' then bytes else 0 end) sga_shared_io_pool,
         sum(case when lower(pool) = 'inmemory area' then bytes else 0 end) sga_inmemory_area,
         sum(case when lower(name) like '%result cache%' then bytes else 0 end) sga_result_cache
  FROM gv$sgastat
  GROUP BY inst_id
),
pga AS (
  SELECT inst_id,
         max(CASE WHEN name='total PGA allocated' THEN value END) pga_allocated,
         max(CASE WHEN name='total PGA inuse' THEN value END) pga_used,
         max(CASE WHEN name='total freeable PGA memory' THEN value END) pga_freeable,
         max(CASE WHEN name='maximum PGA allocated' THEN value END) pga_max_allocated
  FROM gv$pgastat
  WHERE name IN ('total PGA allocated', 'total PGA inuse', 'total freeable PGA memory', 'maximum PGA allocated')
  GROUP BY inst_id
)
SELECT db.database_name || '|' ||
       nvl(inst.instance_name, 'UNKNOWN') || '|' ||
       nvl(inst.host_name, '') || '|' ||
       to_char(SYSDATE,'YYYY-MM-DD HH24:MI:SS') || '|' ||
       nvl(round(params.sga_target/1024/1024/1024,2),0) || '|' ||
       nvl(round(params.sga_max_size/1024/1024/1024,2),0) || '|' ||
       nvl(round(sga.sga_used/1024/1024/1024,2),0) || '|' ||
       round(nvl(sga.sga_fixed,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_redo,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_buffer_cache,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_shared_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_large_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_java_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_streams_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_shared_io_pool,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_inmemory_area,0)/1024/1024/1024,2) || '|' ||
       round(nvl(sga.sga_result_cache,0)/1024/1024/1024,2) || '|' ||
       round(greatest(
         nvl(sga.sga_used,0)
         - nvl(sga.sga_fixed,0)
         - nvl(sga.sga_redo,0)
         - nvl(sga.sga_buffer_cache,0)
         - nvl(sga.sga_shared_pool,0)
         - nvl(sga.sga_large_pool,0)
         - nvl(sga.sga_java_pool,0)
         - nvl(sga.sga_streams_pool,0)
         - nvl(sga.sga_shared_io_pool,0)
         - nvl(sga.sga_inmemory_area,0)
         - nvl(sga.sga_result_cache,0), 0
       )/1024/1024/1024,2) || '|' ||
       nvl(round(params.pga_aggregate_target/1024/1024/1024,2),0) || '|' ||
       nvl(round(params.pga_aggregate_limit/1024/1024/1024,2),0) || '|' ||
       nvl(round(pga.pga_allocated/1024/1024/1024,2),0) || '|' ||
       nvl(round(pga.pga_used/1024/1024/1024,2),0) || '|' ||
       nvl(round(pga.pga_freeable/1024/1024/1024,2),0) || '|' ||
       nvl(round(pga.pga_max_allocated/1024/1024/1024,2),0)
FROM inst
CROSS JOIN db
LEFT JOIN params ON params.inst_id = inst.inst_id
LEFT JOIN sga ON sga.inst_id = inst.inst_id
LEFT JOIN pga ON pga.inst_id = inst.inst_id
ORDER BY inst.instance_name;
exit
""".replace("\r\n", "\n").replace("\r", "\n").lstrip()


def _calculate_sga_other_gb(sga_used_gb: float, *known_component_gb: float) -> float:
    return round(max(sga_used_gb - sum(known_component_gb), 0), 2)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
