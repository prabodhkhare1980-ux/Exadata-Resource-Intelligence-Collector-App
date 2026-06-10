"""Tests for the AWR workload-intensity and tablespace-growth collector."""

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from collectors.db_inventory_collector import DBInventoryRecord
from collectors.db_workload_collector import (
    TABLESPACE_GROWTH_COLUMNS,
    WORKLOAD_COLUMNS,
    DBWorkloadCollector,
    build_db_tablespace_growth_sql,
    build_db_workload_sql,
    parse_db_tablespace_growth_output,
    parse_db_workload_output,
)
from reports.writers import (
    write_db_tablespace_growth_csv,
    write_db_tablespace_growth_json,
    write_db_workload_csv,
    write_db_workload_json,
)
from ssh_runner import CommandResult


class FakeHost:
    name = "node1"
    address = "node1.example.com"
    force_tty = False
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


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------


def test_workload_sql_uses_time_model_and_redo() -> None:
    sql = build_db_workload_sql(7)
    assert "dba_hist_sys_time_model" in sql
    assert "'DB time'" in sql
    assert "'DB CPU'" in sql
    assert "dba_hist_sysstat" in sql
    assert "'redo size'" in sql
    assert "define DAYS_BACK=7" in sql
    assert "sqlplus" not in sql  # builder emits SQL only


def test_workload_sql_clamps_days_back_to_minimum_one() -> None:
    assert "define DAYS_BACK=1" in build_db_workload_sql(0)


def test_tablespace_growth_sql_uses_awr_view() -> None:
    sql = build_db_tablespace_growth_sql(14)
    assert "dba_hist_tbspc_space_usage" in sql
    assert "v$tablespace" in sql
    assert "db_block_size" in sql
    assert "define DAYS_BACK=14" in sql


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_workload_output() -> None:
    rows = parse_db_workload_output(
        "DB1|DB11|2026-06-01 01:00:00|3600|1800.5|900.2|0.5|512.0|0.142\n"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["DB_NAME"] == "DB1"
    assert row["INSTANCE_NAME"] == "DB11"
    assert row["AAS"] == "0.5"
    assert row["REDO_MB"] == "512.0"
    assert row["REDO_MBPS"] == "0.142"


def test_parse_workload_ignores_echoed_sql() -> None:
    stdout = """
SQL> set echo off
WITH tm AS (SELECT ... FROM dba_hist_sys_time_model)
DB1|DB11|2026-06-01 01:00:00|3600|1800.5|900.2|0.5|512.0|0.142
exit
"""
    rows = parse_db_workload_output(stdout)
    assert len(rows) == 1
    assert rows[0]["DB_NAME"] == "DB1"


def test_parse_tablespace_growth_output() -> None:
    rows = parse_db_tablespace_growth_output(
        "DB1|USERS|2026-06-01 01:00:00|100.0|82.5|68.75\n"
        "DB1|SYSAUX|2026-06-01 01:00:00|20.0|15.0|75.0\n"
    )
    assert len(rows) == 2
    assert rows[0]["TABLESPACE_NAME"] == "USERS"
    assert rows[0]["ALLOC_GB"] == "100.0"
    assert rows[0]["USED_GB"] == "82.5"
    assert rows[1]["TABLESPACE_NAME"] == "SYSAUX"


# ---------------------------------------------------------------------------
# Collector behaviour
# ---------------------------------------------------------------------------


def test_collect_host_returns_workload_and_tablespace_rows() -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        if sql_kind == "workload":
            return _result("DB1|DB11|2026-06-01 01:00:00|3600|1800.5|900.2|0.5|512.0|0.142\n")
        if sql_kind == "tablespace_growth":
            return _result("DB1|USERS|2026-06-01 01:00:00|100.0|82.5|68.75\n")
        raise AssertionError(f"unexpected sql_kind {sql_kind}")

    collector = DBWorkloadCollector(runner=None)
    workload, tablespaces = collector.collect_host(
        _inventory_record(), FakeHost(), sql_executor=fake_executor
    )
    assert len(workload) == 1
    assert workload[0].AAS == "0.5"
    assert workload[0].db_unique_name == "DB1_UNQ"
    assert workload[0].collection_status == "success"
    assert len(tablespaces) == 1
    assert tablespaces[0].TABLESPACE_NAME == "USERS"


def test_collect_host_skips_non_open_db() -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        raise AssertionError("should not run SQL for a mounted standby")

    collector = DBWorkloadCollector(runner=None)
    workload, tablespaces = collector.collect_host(
        _inventory_record(open_mode="MOUNTED"), FakeHost(), sql_executor=fake_executor
    )
    assert workload == []
    assert tablespaces == []


def test_collect_host_records_awr_failure() -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        return _result(stdout="ORA-00942: table or view does not exist", returncode=942)

    collector = DBWorkloadCollector(runner=None)
    workload, tablespaces = collector.collect_host(
        _inventory_record(), FakeHost(), sql_executor=fake_executor
    )
    assert workload[0].collection_status == "failed"
    assert workload[0].error_category == "AWR_UNAVAILABLE_OR_PRIVILEGE"
    assert tablespaces[0].collection_status == "failed"


def test_collect_host_disabled_when_use_awr_false() -> None:
    collector = DBWorkloadCollector(runner=None)
    workload, tablespaces = collector.collect_host(
        _inventory_record(), FakeHost(), use_awr=False
    )
    assert workload == []
    assert tablespaces == []


def test_collect_host_respects_collect_flags() -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        assert sql_kind == "workload"
        return _result("DB1|DB11|2026-06-01 01:00:00|3600|1800.5|900.2|0.5|512.0|0.142\n")

    collector = DBWorkloadCollector(runner=None)
    workload, tablespaces = collector.collect_host(
        _inventory_record(), FakeHost(),
        collect_tablespace_growth=False, sql_executor=fake_executor,
    )
    assert len(workload) == 1
    assert tablespaces == []


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def test_write_workload_and_tablespace_outputs(tmp_path: Path) -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        if sql_kind == "workload":
            return _result("DB1|DB11|2026-06-01 01:00:00|3600|1800.5|900.2|0.5|512.0|0.142\n")
        return _result("DB1|USERS|2026-06-01 01:00:00|100.0|82.5|68.75\n")

    collector = DBWorkloadCollector(runner=None)
    workload, tablespaces = collector.collect_host(
        _inventory_record(), FakeHost(), sql_executor=fake_executor
    )

    wcsv = write_db_workload_csv(workload, tmp_path)
    wjson = write_db_workload_json(workload, tmp_path)
    assert wcsv.exists() and wjson.exists()
    wpayload = json.loads(wjson.read_text())
    assert wpayload[0]["AAS"] == "0.5"
    assert set(wpayload[0].keys()) == set(WORKLOAD_COLUMNS)

    tcsv = write_db_tablespace_growth_csv(tablespaces, tmp_path)
    tjson = write_db_tablespace_growth_json(tablespaces, tmp_path)
    assert tcsv.exists() and tjson.exists()
    tpayload = json.loads(tjson.read_text())
    assert tpayload[0]["TABLESPACE_NAME"] == "USERS"
    assert set(tpayload[0].keys()) == set(TABLESPACE_GROWTH_COLUMNS)
