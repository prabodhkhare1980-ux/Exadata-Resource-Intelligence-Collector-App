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
    _build_db_performance_sql,
    _db_perf_error_category,
    parse_db_memory_output,
    parse_db_performance_output,
)
from reports.writers import (
    build_health_summary_rows,
    write_db_memory_history_csv,
    write_db_memory_history_json,
    write_db_performance_csv,
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
    row = parse_db_performance_output("DB1|DB11|node1|2026-06-01 00:00:00|10|2|12|20|5|25|100|50|150|200|100|300|3.5|7.5|84.9|90.1\n")[0]
    assert row["DB_NAME"] == "DB1"
    assert row["INSTANCE_NAME"] == "DB11"
    assert row["TOTAL_IOPS_AVG"] == "12"
    assert row["HOST_CPU_UTIL_PCT_MAX"] == "90.1"


def test_write_thrpt_mapping_uses_physical_write_bytes_for_write_thrpt() -> None:
    sql = _build_db_performance_sql(7)
    assert "'Physical Read Total Bytes Per Sec' AS read_thrpt" in sql
    assert "'Physical Write Total Bytes Per Sec' AS write_thrpt" in sql
    assert "'Physical Read Total Bytes Per Sec' AS write_thrpt" not in sql


def test_ora_00942_handling_marks_awr_unavailable() -> None:
    def executor(oracle_home: str, sid: str, sql: str, sql_kind: str) -> CommandResult:
        return _result(stdout="ORA-00942: table or view does not exist\n", returncode=942)

    perf, mem = DBPerformanceCollector(None).collect_host(_inventory_record(), FakeHost(), sql_executor=executor)
    assert perf[0].collection_status == "failed"
    assert perf[0].error_category == AWR_ERROR_CATEGORY
    assert mem[0].error_category == AWR_ERROR_CATEGORY
    assert _db_perf_error_category("ORA-01031: insufficient privileges", "") == AWR_ERROR_CATEGORY


def test_csv_json_output_generation(tmp_path: Path) -> None:
    perf = [DBPerformanceRecord(Cluster="c1", HOST_NAME="node1", DB_NAME="DB1", INSTANCE_NAME="DB11", END_TIME="2026-06-01 00:00:00", TOTAL_IOPS_AVG="12", Collected_At="now")]
    mem = [DBMemoryHistoryRecord(Cluster="c1", HOST_NAME="node1", DB_NAME="DB1", INSTANCE_NAME="DB11", END_TIME="2026-06-01 00:00:00", SGA_USED_GB="9", Collected_At="now")]

    write_db_performance_csv(perf, tmp_path)
    write_db_performance_json(perf, tmp_path)
    write_db_memory_history_csv(mem, tmp_path)
    write_db_memory_history_json(mem, tmp_path)

    with (tmp_path / "db_performance.csv").open(encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows[0]["TOTAL_IOPS_AVG"] == "12"
    assert json.loads((tmp_path / "db_performance.json").read_text(encoding="utf-8"))[0]["DB_NAME"] == "DB1"
    with (tmp_path / "db_memory_history.csv").open(encoding="utf-8") as csv_file:
        mem_rows = list(csv.DictReader(csv_file))
    assert mem_rows[0]["SGA_USED_GB"] == "9"
    assert json.loads((tmp_path / "db_memory_history.json").read_text(encoding="utf-8"))[0]["SGA_USED_GB"] == "9"


def test_parse_memory_sql_output() -> None:
    row = parse_db_memory_output("DB1|DB11|node1|2026-06-01 00:00:00|10|12|9|4|8|7|6|1|7.5\n")[0]
    assert row["SGA_TARGET_GB"] == "10"
    assert row["PGA_ALLOCATED_GB"] == "7"
    assert row["PGA_MAX_ALLOCATED_GB"] == "7.5"


def test_sga_pga_warning_logic() -> None:
    mem_records = [
        DBMemoryHistoryRecord(Cluster="c1", HOST_NAME="node1", DB_NAME="DB1", INSTANCE_NAME="DB11", SGA_TARGET_GB="10", SGA_USED_GB="9", PGA_AGGREGATE_LIMIT_GB="10", PGA_ALLOCATED_GB="9.8", Collected_At="now"),
    ]
    rows = build_health_summary_rows([], [], [], [], db_memory_records=mem_records)
    sga = next(row for row in rows if row["metric"] == "sga_used_pct_of_target")
    pga = next(row for row in rows if row["metric"] == "pga_allocated_pct_of_limit")
    assert sga["warning_level"] == "WARNING"
    assert pga["warning_level"] == "CRITICAL"


def test_missing_memory_view_handling_does_not_fail_host() -> None:
    def executor(oracle_home: str, sid: str, sql: str, sql_kind: str) -> CommandResult:
        if sql_kind == "performance":
            return _result(stdout="DB1|DB11|node1|2026-06-01 00:00:00|1|1|2|1|1|2|1|1|2|1|1|2|1|1|50|60\n")
        return _result(stdout="ORA-00942: table or view does not exist\n", returncode=942)

    perf, mem = DBPerformanceCollector(None).collect_host(_inventory_record(), FakeHost(), sql_executor=executor)
    assert perf[0].collection_status == "success"
    assert mem[0].collection_status == "failed"
    assert mem[0].error_category == AWR_ERROR_CATEGORY
