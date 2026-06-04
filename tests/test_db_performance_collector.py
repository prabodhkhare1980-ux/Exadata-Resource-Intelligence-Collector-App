import csv
import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from collectors.db_inventory_collector import DBInventoryRecord
from collectors.db_performance_collector import (
    AWR_ERROR_CATEGORY,
    DBMemoryHistoryRecord,
    DBPerformanceCollector,
    DBPerformanceRecord,
    _build_db_memory_sql,
    _build_db_performance_sql,
    _db_perf_error_category,
    parse_db_memory_output,
    parse_db_performance_output,
)
from reports.writers import (
    build_health_summary_rows,
    write_db_memory_history_csv,
    write_db_memory_history_errors_csv,
    write_db_memory_history_errors_json,
    write_db_memory_history_json,
    write_db_performance_csv,
    write_db_performance_errors_csv,
    write_db_performance_errors_json,
    write_db_performance_json,
)
from ssh_runner import CommandResult


class FakeHost:
    name = "node1"
    address = "node1.example.com"
    user = "srcordma"
    port = 22
    strict_host_key_checking = "accept-new"
    auth_method = "ssh_key"
    private_key = ".secrets/ssh/srcordma_id_rsa"
    force_tty = False
    timeout_seconds = 120
    environment = "onprem"


def _result(stdout: str = "", stderr: str = "", returncode: int = 0) -> CommandResult:
    return CommandResult(FakeHost(), [], stdout, stderr, returncode)


def _inventory_record(open_mode: str = "READ WRITE") -> DBInventoryRecord:
    return DBInventoryRecord(
        cluster="c1",
        host="node1",
        address="10.0.0.1",
        collected_at="now",
        status="ok",
        db_resource_details=[
            {
                "collection_status": "success",
                "db_unique_name": "DB1_UNQ",
                "DB_NAME": "DB1",
                "OPEN_MODE": open_mode,
                "oracle_home": "/u01/app/oracle/product/19/dbhome_1",
                "oracle_sid": "DB11",
            }
        ],
    )


def test_parse_pipe_delimited_db_performance_sql_output() -> None:
    row = parse_db_performance_output(
        "DB1|DB11|node1|2026-06-01 00:00:00|10|2|12|20|5|25|100|50|150|200|100|300|3.5|7.5|84.9|90.1\n"
    )[0]
    assert row["DB_NAME"] == "DB1"
    assert row["INSTANCE_NAME"] == "DB11"
    assert row["TOTAL_IOPS_AVG"] == "12"
    assert row["HOST_CPU_UTIL_PCT_MAX"] == "90.1"


def test_parse_ignores_echoed_sql_and_uses_valid_rows() -> None:
    stdout = """
SQL> set echo off
WITH data1 AS (
SELECT database_name || '|' || instance_name FROM somewhere
DB1|DB11|node1|2026-06-01 00:00:00|10|2|12|20|5|25|100|50|150|200|100|300|3.5|7.5|84.9|90.1
exit
"""
    rows = parse_db_performance_output(stdout)
    assert len(rows) == 1
    assert rows[0]["DB_NAME"] == "DB1"


def test_write_thrpt_mapping_uses_physical_write_bytes_for_write_thrpt() -> None:
    sql = _build_db_performance_sql(7)
    assert "sqlplus" not in sql
    assert "set echo off" in sql
    assert "set termout off" in sql
    assert "'Physical Read Total Bytes Per Sec' AS read_thrpt" in sql
    assert "'Physical Write Total Bytes Per Sec' AS write_thrpt" in sql
    assert "'Physical Read Total Bytes Per Sec' AS write_thrpt" not in sql


def test_ora_00942_handling_marks_awr_unavailable() -> None:
    def executor(oracle_home: str, sid: str, sql: str, sql_kind: str) -> CommandResult:
        return _result(
            stdout="ORA-00942: table or view does not exist\n", returncode=942
        )

    perf, mem = DBPerformanceCollector(None).collect_host(
        _inventory_record(), FakeHost(), sql_executor=executor
    )
    assert perf[0].collection_status == "failed"
    assert perf[0].error_category == AWR_ERROR_CATEGORY
    assert mem[0].error_category == AWR_ERROR_CATEGORY
    assert (
        _db_perf_error_category("ORA-01031: insufficient privileges", "")
        == AWR_ERROR_CATEGORY
    )


def test_memory_awr_sql_resolves_instance_name_from_database_instance() -> None:
    sql = _build_db_memory_sql(7).lower()
    assert "snaps.instance_name" not in sql
    assert "from dba_hist_database_instance" in sql
    assert "nvl(inst.instance_name, 'unknown')" in sql
    assert "inst.dbid = snaps.dbid" in sql
    assert "inst.instance_number = snaps.instance_number" in sql
    assert "inst.startup_time = snaps.startup_time" in sql


def test_memory_awr_sqlplus_hygiene_settings_are_explicit() -> None:
    sql = _build_db_memory_sql(7).lower()
    assert "set echo off" in sql
    assert "set termout off" in sql
    assert "set feedback off" in sql
    assert "set heading off" in sql
    assert "set verify off" in sql
    assert "set pages 0" in sql
    assert "set lines 32767" in sql
    assert "set trimspool on" in sql
    assert "set tab off" in sql


def test_ora_00904_maps_to_sql_bug_without_current_fallback() -> None:
    def executor(oracle_home: str, sid: str, sql: str, sql_kind: str) -> CommandResult:
        return _result(
            stdout='ORA-00904: "INSTANCE_NAME": invalid identifier\n', returncode=904
        )

    perf, mem = DBPerformanceCollector(None).collect_host(
        _inventory_record(),
        FakeHost(),
        collect_cpu_iops=False,
        collect_memory_history=True,
        sql_executor=executor,
    )
    assert perf == []
    assert mem[0].collection_status == "failed"
    assert mem[0].error_category == "SQL_BUG"
    assert mem[0].size_source == "AWR"


def test_memory_sql_payload_sent_only_once_and_success_does_not_store_sql_stdout() -> (
    None
):
    calls: list[str] = []

    def executor(oracle_home: str, sid: str, sql: str, sql_kind: str) -> CommandResult:
        assert sql_kind == "memory"
        calls.append(sql)
        return _result(
            stdout="DB1|DB11|node1|2026-06-01 00:00:00|10|12|9|4|8|7|6|1|7.5\n"
        )

    perf, mem = DBPerformanceCollector(None).collect_host(
        _inventory_record(),
        FakeHost(),
        collect_cpu_iops=False,
        collect_memory_history=True,
        sql_executor=executor,
    )
    assert perf == []
    assert len(calls) == 1
    assert calls[0].count("WITH snaps AS") == 1
    assert mem[0].collection_status == "success"
    assert mem[0].sql_stdout == ""
    assert "WITH snaps AS" not in mem[0].sql_stdout


def test_csv_json_output_generation_filters_errors_and_deduplicates(
    tmp_path: Path,
) -> None:
    perf = [
        DBPerformanceRecord(
            Cluster="c1",
            HOST_NAME="node1",
            DB_NAME="DB1",
            INSTANCE_NAME="DB11",
            END_TIME="2026-06-01 00:00:00",
            TOTAL_IOPS_AVG="12",
            Collected_At="now",
            db_unique_name="DB1_UNQ",
            source_host="node1",
            source_address="10.0.0.1",
            source_oracle_sid="DB11",
        ),
        DBPerformanceRecord(
            Cluster="c1",
            HOST_NAME="node1",
            DB_NAME="DB1",
            INSTANCE_NAME="DB11",
            END_TIME="2026-06-01 00:00:00",
            TOTAL_IOPS_AVG="12",
            Collected_At="now",
            db_unique_name="DB1_UNQ",
            source_host="node2",
            source_address="10.0.0.2",
            source_oracle_sid="DB12",
        ),
        DBPerformanceRecord(
            Cluster="c1",
            HOST_NAME="node1",
            DB_NAME="DB1",
            INSTANCE_NAME="DB11",
            END_TIME="",
            Collected_At="now",
            collection_status="failed",
            collection_error="bad parse",
            sql_stdout="select x from y",
        ),
    ]
    mem = [
        DBMemoryHistoryRecord(
            Cluster="c1",
            HOST_NAME="node1",
            DB_NAME="DB1",
            INSTANCE_NAME="DB11",
            END_TIME="2026-06-01 00:00:00",
            SGA_USED_GB="9",
            Collected_At="now",
            db_unique_name="DB1_UNQ",
        ),
        DBMemoryHistoryRecord(
            Cluster="c1",
            HOST_NAME="node1",
            DB_NAME="DB1",
            INSTANCE_NAME="DB11",
            END_TIME="",
            Collected_At="now",
            collection_status="failed",
            sql_stdout="ORA-00942",
        ),
    ]

    write_db_performance_csv(perf, tmp_path)
    write_db_performance_json(perf, tmp_path)
    write_db_performance_errors_csv(perf, tmp_path)
    write_db_performance_errors_json(perf, tmp_path)
    write_db_memory_history_csv(mem, tmp_path)
    write_db_memory_history_json(mem, tmp_path)
    write_db_memory_history_errors_csv(mem, tmp_path)
    write_db_memory_history_errors_json(mem, tmp_path)

    with (tmp_path / "db_performance.csv").open(encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == 1
    assert rows[0]["TOTAL_IOPS_AVG"] == "12"
    assert rows[0]["duplicate_count"] == "2"
    perf_json = json.loads(
        (tmp_path / "db_performance.json").read_text(encoding="utf-8")
    )
    assert perf_json[0]["DB_NAME"] == "DB1"
    assert "sql_stdout" not in perf_json[0]
    perf_errors = json.loads(
        (tmp_path / "db_performance_errors.json").read_text(encoding="utf-8")
    )
    assert perf_errors[0]["sql_stdout"] == "select x from y"
    with (tmp_path / "db_memory_history.csv").open(encoding="utf-8") as csv_file:
        mem_rows = list(csv.DictReader(csv_file))
    assert mem_rows[0]["SGA_USED_GB"] == "9"
    assert (
        json.loads((tmp_path / "db_memory_history.json").read_text(encoding="utf-8"))[
            0
        ]["SGA_USED_GB"]
        == "9"
    )
    assert (
        json.loads(
            (tmp_path / "db_memory_history_errors.json").read_text(encoding="utf-8")
        )[0]["sql_stdout"]
        == "ORA-00942"
    )


def test_parse_memory_sql_output() -> None:
    row = parse_db_memory_output(
        "DB1|DB11|node1|2026-06-01 00:00:00|10|12|9|4|8|7|6|1|7.5\n"
    )[0]
    assert row["SGA_TARGET_GB"] == "10"
    assert row["PGA_ALLOCATED_GB"] == "7"
    assert row["PGA_MAX_ALLOCATED_GB"] == "7.5"


def test_sga_pga_warning_logic() -> None:
    mem_records = [
        DBMemoryHistoryRecord(
            Cluster="c1",
            HOST_NAME="node1",
            DB_NAME="DB1",
            INSTANCE_NAME="DB11",
            SGA_TARGET_GB="10",
            SGA_USED_GB="9",
            PGA_AGGREGATE_LIMIT_GB="10",
            PGA_ALLOCATED_GB="9.8",
            Collected_At="now",
        ),
    ]
    rows = build_health_summary_rows([], [], [], [], db_memory_records=mem_records)
    sga = next(row for row in rows if row["metric"] == "sga_used_pct_of_target")
    pga = next(row for row in rows if row["metric"] == "pga_allocated_pct_of_limit")
    assert sga["warning_level"] == "WARNING"
    assert pga["warning_level"] == "CRITICAL"


def test_missing_memory_view_handling_does_not_fail_host() -> None:
    def executor(oracle_home: str, sid: str, sql: str, sql_kind: str) -> CommandResult:
        if sql_kind == "performance":
            return _result(
                stdout="DB1|DB11|node1|2026-06-01 00:00:00|1|1|2|1|1|2|1|1|2|1|1|2|1|1|50|60\n"
            )
        return _result(
            stdout="ORA-00942: table or view does not exist\n", returncode=942
        )

    perf, mem = DBPerformanceCollector(None).collect_host(
        _inventory_record(), FakeHost(), sql_executor=executor
    )
    assert perf[0].collection_status == "success"
    assert mem[0].collection_status == "failed"
    assert mem[0].error_category == AWR_ERROR_CATEGORY


def _inventory_record_for(
    host: str, sid: str, db_unique_name: str = "DB1_UNQ"
) -> DBInventoryRecord:
    return DBInventoryRecord(
        cluster="c1",
        host=host,
        address=f"10.0.0.{1 if host == 'node1' else 2}",
        collected_at="now",
        status="ok",
        db_resource_details=[
            {
                "collection_status": "success",
                "db_unique_name": db_unique_name,
                "DB_NAME": "DB1",
                "OPEN_MODE": "READ WRITE",
                "oracle_home": "/u01/app/oracle/product/19/dbhome_1",
                "oracle_sid": sid,
            }
        ],
    )


class FakeHost2(FakeHost):
    name = "node2"
    address = "node2.example.com"


def _new_memory_row(
    instance: str = "DB11", end_time: str = "2026-06-01 00:00:00"
) -> str:
    return f"DB1|{instance}|node1|{end_time}|10|12|9|1|0.5|3|2|0.25|0.1|0.05|0.02|0.75|0.33|1|4|8|7|6|1|7.5\n"


def test_memory_awr_sql_contains_sga_component_columns() -> None:
    sql = _build_db_memory_sql(7).lower()
    assert "sga_fixed" in sql
    assert "sga_redo" in sql
    assert "sga_buffer_cache" in sql
    assert "sga_shared_pool" in sql
    assert "sga_result_cache" in sql
    assert "greatest(" in sql
    assert "from dba_hist_sgastat" in sql


def test_parse_memory_sql_output_with_sga_components_and_legacy_rows() -> None:
    new_row = parse_db_memory_output(_new_memory_row())[0]
    assert new_row["SGA_FIXED_GB"] == "1"
    assert new_row["SGA_OTHER_GB"] == "1"
    legacy_row = parse_db_memory_output(
        "DB1|DB11|node1|2026-06-01 00:00:00|10|12|9|4|8|7|6|1|7.5\n"
    )[0]
    assert legacy_row["SGA_TARGET_GB"] == "10"
    assert legacy_row["SGA_FIXED_GB"] == ""
    assert legacy_row["PGA_MAX_ALLOCATED_GB"] == "7.5"


def test_memory_csv_writer_includes_sga_component_columns(tmp_path: Path) -> None:
    write_db_memory_history_csv(
        [
            DBMemoryHistoryRecord(
                Cluster="c1",
                HOST_NAME="node1",
                DB_NAME="DB1",
                INSTANCE_NAME="DB11",
                END_TIME="2026-06-01 00:00:00",
                SGA_USED_GB="9",
                SGA_FIXED_GB="1",
                SGA_OTHER_GB="2",
                Collected_At="now",
                db_unique_name="DB1_UNQ",
            )
        ],
        tmp_path,
    )
    with (tmp_path / "db_memory_history.csv").open(encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert "SGA_FIXED_GB" in rows[0]
    assert "SGA_OTHER_GB" in rows[0]


def test_sga_other_gb_calculation() -> None:
    from collectors.db_performance_collector import _calculate_sga_other_gb

    assert _calculate_sga_other_gb(10, 1, 2, 3) == 4
    assert _calculate_sga_other_gb(3, 1, 2, 3) == 0


def test_current_memory_sql_returns_gv_sgastat_component_columns() -> None:
    from collectors.db_performance_collector import _build_db_memory_current_sql

    sql = _build_db_memory_current_sql().lower()
    assert "from gv$sgastat" in sql
    assert "sga_fixed" in sql
    assert "sga_result_cache" in sql
    assert "greatest(" in sql


def test_cluster_memory_collects_same_db_unique_name_once() -> None:
    calls: list[str] = []

    def executor(oracle_home: str, sid: str, sql: str, sql_kind: str) -> CommandResult:
        calls.append(sid)
        return _result(stdout=_new_memory_row(instance="DB11"))

    records = DBPerformanceCollector(None).collect_cluster_memory_history(
        [
            _inventory_record_for("node1", "DB11"),
            _inventory_record_for("node2", "DB12"),
        ],
        {"node1": FakeHost(), "node2": FakeHost2()},
        sql_executor=executor,
    )
    success = [record for record in records if record.collection_status == "success"]
    skipped = [
        record
        for record in records
        if record.collection_source_reason == "skipped_duplicate"
    ]
    assert calls == ["DB11"]
    assert len(success) == 1
    assert success[0].collection_scope == "cluster_db_unique_name"
    assert success[0].collection_source_selected is True
    assert success[0].collection_source_reason == "primary_selected"
    assert len(skipped) == 1


def test_cluster_memory_retries_second_host_when_first_source_fails() -> None:
    calls: list[str] = []

    def executor(oracle_home: str, sid: str, sql: str, sql_kind: str) -> CommandResult:
        calls.append(sid)
        if sid == "DB11":
            return _result(stdout="ORA-01555: snapshot too old\n", returncode=1555)
        return _result(stdout=_new_memory_row(instance="DB12"))

    records = DBPerformanceCollector(None).collect_cluster_memory_history(
        [
            _inventory_record_for("node1", "DB11"),
            _inventory_record_for("node2", "DB12"),
        ],
        {"node1": FakeHost(), "node2": FakeHost2()},
        sql_executor=executor,
    )
    success = [record for record in records if record.collection_status == "success"]
    assert calls == ["DB11", "DB12"]
    assert len(success) == 1
    assert success[0].source_oracle_sid == "DB12"
    assert success[0].collection_source_reason == "retry_selected"


def test_memory_writer_removes_duplicate_cluster_db_unique_instance_end_time_rows(
    tmp_path: Path,
) -> None:
    records = [
        DBMemoryHistoryRecord(
            Cluster="c1",
            HOST_NAME="node1",
            DB_NAME="DB1",
            INSTANCE_NAME="DB11",
            END_TIME="2026-06-01 00:00:00",
            SGA_USED_GB="9",
            Collected_At="now",
            db_unique_name="DB1_UNQ",
        ),
        DBMemoryHistoryRecord(
            Cluster="c1",
            HOST_NAME="node2",
            DB_NAME="DB1",
            INSTANCE_NAME="DB11",
            END_TIME="2026-06-01 00:00:00",
            SGA_USED_GB="9",
            Collected_At="now",
            db_unique_name="DB1_UNQ",
        ),
    ]
    write_db_memory_history_csv(records, tmp_path)
    with (tmp_path / "db_memory_history.csv").open(encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == 1
    assert rows[0]["duplicate_count"] == "1"
