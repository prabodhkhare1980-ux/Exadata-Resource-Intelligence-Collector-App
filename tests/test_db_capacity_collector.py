"""Tests for the DB license/capacity collector (PDB inventory + feature usage)."""

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from collectors.db_inventory_collector import DBInventoryRecord
from collectors.db_capacity_collector import (
    DBCapacityCollector,
    FEATURE_USAGE_COLUMNS,
    PDB_INVENTORY_COLUMNS,
    build_feature_usage_sql,
    build_pdb_inventory_sql,
    parse_feature_usage_output,
    parse_pdb_inventory_output,
)
from reports.writers import (
    write_feature_usage_csv,
    write_feature_usage_json,
    write_pdb_inventory_csv,
    write_pdb_inventory_json,
)
from ssh_runner import CommandResult


class FakeHost:
    name = "node1"
    address = "node1.example.com"
    force_tty = False
    environment = "onprem"


def _result(stdout: str = "", stderr: str = "", returncode: int = 0) -> CommandResult:
    return CommandResult(FakeHost(), [], stdout, stderr, returncode)


def _inventory_record() -> DBInventoryRecord:
    return DBInventoryRecord(
        cluster="c1",
        host="node1",
        address="10.0.0.1",
        collected_at="now",
        status="ok",
        db_resource_details=[
            {
                "collection_status": "success",
                "db_unique_name": "CDB1_UNQ",
                "DB_NAME": "CDB1",
                "OPEN_MODE": "READ WRITE",
                "oracle_home": "/u01/app/oracle/product/19/dbhome_1",
                "oracle_sid": "CDB11",
            }
        ],
    )


# ---------------------------------------------------------------------------
# SQL builders
# ---------------------------------------------------------------------------


def test_pdb_inventory_sql_targets_vpdbs_and_excludes_seed() -> None:
    sql = build_pdb_inventory_sql()
    assert "v$pdbs" in sql
    assert "cdb_data_files" in sql
    assert "con_id > 2" in sql  # excludes CDB$ROOT (1) and PDB$SEED (2)
    assert "sqlplus" not in sql  # builder emits SQL only, not the shell command


def test_feature_usage_sql_uses_latest_sample_and_currently_used() -> None:
    sql = build_feature_usage_sql()
    assert "dba_feature_usage_statistics" in sql
    assert "currently_used = 'TRUE'" in sql
    assert "ROW_NUMBER()" in sql  # one row per feature, latest sample


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_pdb_inventory_output() -> None:
    rows = parse_pdb_inventory_output(
        "CDB1|PDB1|3|READ WRITE|NO|125.5\nCDB1|PDB2|4|MOUNTED|NO|0\n"
    )
    assert len(rows) == 2
    assert rows[0]["PDB_NAME"] == "PDB1"
    assert rows[0]["CON_ID"] == "3"
    assert rows[0]["OPEN_MODE"] == "READ WRITE"
    assert rows[0]["TOTAL_SIZE_GB"] == "125.5"
    assert rows[1]["PDB_NAME"] == "PDB2"


def test_parse_pdb_inventory_tolerates_empty_result() -> None:
    # A non-CDB legitimately returns no rows; the parser must not raise.
    assert parse_pdb_inventory_output("\n\n") == []


def test_parse_feature_usage_output() -> None:
    rows = parse_feature_usage_output(
        "CDB1|Partitioning|TRUE|42|2024-01-01|2026-06-01\n"
        "CDB1|Advanced Compression|TRUE|7|2025-02-02|2026-05-01\n"
    )
    assert len(rows) == 2
    assert rows[0]["FEATURE_NAME"] == "Partitioning"
    assert rows[0]["CURRENTLY_USED"] == "TRUE"
    assert rows[0]["DETECTED_USAGES"] == "42"
    assert rows[1]["FEATURE_NAME"] == "Advanced Compression"


def test_parse_ignores_echoed_sql_lines() -> None:
    stdout = """
SQL> set echo off
SELECT db_name || '|' || feature_name FROM somewhere
CDB1|In-Memory Column Store|TRUE|3|2025-01-01|2026-01-01
exit
"""
    rows = parse_feature_usage_output(stdout)
    assert len(rows) == 1
    assert rows[0]["FEATURE_NAME"] == "In-Memory Column Store"


# ---------------------------------------------------------------------------
# Collector behaviour (with a fake sql_executor)
# ---------------------------------------------------------------------------


def test_collect_host_returns_pdb_and_feature_rows() -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        if sql_kind == "pdb_inventory":
            return _result("CDB1|PDB1|3|READ WRITE|NO|100\nCDB1|PDB2|4|READ WRITE|NO|50\n")
        if sql_kind == "feature_usage":
            return _result("CDB1|Partitioning|TRUE|10|2024-01-01|2026-06-01\n")
        raise AssertionError(f"unexpected sql_kind {sql_kind}")

    collector = DBCapacityCollector(runner=None)
    pdbs, features = collector.collect_host(
        _inventory_record(), FakeHost(), sql_executor=fake_executor
    )
    assert [p.PDB_NAME for p in pdbs] == ["PDB1", "PDB2"]
    assert pdbs[0].db_unique_name == "CDB1_UNQ"
    assert pdbs[0].collection_status == "success"
    assert [f.FEATURE_NAME for f in features] == ["Partitioning"]
    assert features[0].collection_status == "success"


def test_collect_host_records_non_cdb_as_no_pdbs() -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        return _result("")  # clean run, no rows

    collector = DBCapacityCollector(runner=None)
    pdbs, features = collector.collect_host(
        _inventory_record(), FakeHost(), sql_executor=fake_executor
    )
    assert len(pdbs) == 1
    assert pdbs[0].collection_status == "success"
    assert pdbs[0].collection_error == "no_pluggable_databases"
    assert features[0].collection_error == "no_tracked_features"


def test_collect_host_records_sql_failure() -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        return _result(stdout="ORA-00942: table or view does not exist", returncode=942)

    collector = DBCapacityCollector(runner=None)
    pdbs, features = collector.collect_host(
        _inventory_record(), FakeHost(), sql_executor=fake_executor
    )
    assert pdbs[0].collection_status == "failed"
    assert "ORA-00942" in pdbs[0].collection_error
    assert features[0].collection_status == "failed"


def test_collect_host_respects_disabled_flags() -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        return _result("CDB1|PDB1|3|READ WRITE|NO|100\n")

    collector = DBCapacityCollector(runner=None)
    pdbs, features = collector.collect_host(
        _inventory_record(),
        FakeHost(),
        collect_feature_usage=False,
        sql_executor=fake_executor,
    )
    assert len(pdbs) == 1
    assert features == []


def test_collect_host_disabled_returns_nothing() -> None:
    collector = DBCapacityCollector(runner=None)
    pdbs, features = collector.collect_host(
        _inventory_record(), FakeHost(), enabled=False
    )
    assert pdbs == []
    assert features == []


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def test_write_pdb_inventory_outputs(tmp_path: Path) -> None:
    def fake_executor(oracle_home, sid, sql, sql_kind):
        if sql_kind == "pdb_inventory":
            return _result("CDB1|PDB1|3|READ WRITE|NO|100\n")
        return _result("CDB1|Partitioning|TRUE|10|2024-01-01|2026-06-01\n")

    collector = DBCapacityCollector(runner=None)
    pdbs, features = collector.collect_host(
        _inventory_record(), FakeHost(), sql_executor=fake_executor
    )

    csv_path = write_pdb_inventory_csv(pdbs, tmp_path)
    json_path = write_pdb_inventory_json(pdbs, tmp_path)
    assert csv_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload[0]["PDB_NAME"] == "PDB1"
    assert set(payload[0].keys()) == set(PDB_INVENTORY_COLUMNS)

    fcsv = write_feature_usage_csv(features, tmp_path)
    fjson = write_feature_usage_json(features, tmp_path)
    assert fcsv.exists() and fjson.exists()
    fpayload = json.loads(fjson.read_text())
    assert fpayload[0]["FEATURE_NAME"] == "Partitioning"
    assert set(fpayload[0].keys()) == set(FEATURE_USAGE_COLUMNS)
