"""Tests for the OPatch (opatch lspatches) per-home inventory collector."""

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from collectors.db_inventory_collector import DBInventoryRecord
from collectors.db_patch_collector import (
    DB_PATCH_COLUMNS,
    DBPatchCollector,
    build_opatch_lspatches_command,
    parse_opatch_lspatches_output,
)
from reports.writers import (
    write_db_patch_inventory_csv,
    write_db_patch_inventory_json,
)
from ssh_runner import CommandResult


class FakeHost:
    name = "node1"
    address = "node1.example.com"
    force_tty = False
    environment = "onprem"


def _result(stdout: str = "", stderr: str = "", returncode: int = 0, timed_out: bool = False) -> CommandResult:
    return CommandResult(FakeHost(), [], stdout, stderr, returncode, timed_out)


def _inventory_record(homes=("/u01/app/oracle/product/19/dbhome_1",), grid_home="/u01/app/19/grid") -> DBInventoryRecord:
    details = [
        {
            "collection_status": "success",
            "db_unique_name": f"DB{i}",
            "oracle_home": home,
            "oracle_sid": f"DB{i}1",
        }
        for i, home in enumerate(homes, start=1)
    ]
    return DBInventoryRecord(
        cluster="c1",
        host="node1",
        address="10.0.0.1",
        collected_at="now",
        status="ok",
        db_resource_details=details,
        grid_home=grid_home,
        grid_owner="grid",
    )


SAMPLE_LSPATCHES = """37499406;OJVM RELEASE UPDATE: 19.22.0.0.240116 (37499406)
37260974;Database Release Update : 19.22.0.0.240116 (37260974)

OPatch succeeded.
"""


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------


def test_build_opatch_command_uses_home_owner_and_opatch_path() -> None:
    cmd = build_opatch_lspatches_command("/u01/app/oracle/product/19/dbhome_1", "oracle", 60)
    assert "sudo -n -u oracle" in cmd
    assert "ORACLE_HOME=/u01/app/oracle/product/19/dbhome_1" in cmd
    assert "/u01/app/oracle/product/19/dbhome_1/OPatch/opatch lspatches" in cmd
    assert "timeout 60s" in cmd


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_lspatches_extracts_patch_rows() -> None:
    rows = parse_opatch_lspatches_output(SAMPLE_LSPATCHES)
    assert len(rows) == 2
    assert rows[0]["PATCH_ID"] == "37499406"
    assert "OJVM RELEASE UPDATE" in rows[0]["PATCH_DESCRIPTION"]
    assert rows[1]["PATCH_ID"] == "37260974"


def test_parse_lspatches_handles_no_patches() -> None:
    text = "There are no Interim patches installed in this Oracle Home.\n\nOPatch succeeded.\n"
    assert parse_opatch_lspatches_output(text) == []


def test_parse_lspatches_ignores_non_patch_lines() -> None:
    rows = parse_opatch_lspatches_output("OPatch succeeded.\nrandom text without semicolon\n")
    assert rows == []


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


def test_collect_host_covers_db_and_grid_homes() -> None:
    seen_homes = []

    def fake_executor(oracle_home, owner, command):
        seen_homes.append((oracle_home, owner))
        return _result(SAMPLE_LSPATCHES)

    collector = DBPatchCollector(runner=None)
    records = collector.collect_host(
        _inventory_record(), FakeHost(), command_executor=fake_executor
    )
    # 2 patches x (1 db home + 1 grid home) = 4 rows.
    assert len(records) == 4
    home_types = {r.HOME_TYPE for r in records}
    assert home_types == {"db", "grid"}
    # Grid home owner comes from the inventory record.
    grid_rows = [r for r in records if r.HOME_TYPE == "grid"]
    assert grid_rows[0].HOME_OWNER == "grid"
    assert all(r.patch_count == 2 for r in records)


def test_collect_host_dedupes_shared_home() -> None:
    calls = []

    def fake_executor(oracle_home, owner, command):
        calls.append(oracle_home)
        return _result(SAMPLE_LSPATCHES)

    # Two DBs sharing the same home plus a distinct grid home.
    inv = _inventory_record(
        homes=("/u01/app/oracle/product/19/dbhome_1", "/u01/app/oracle/product/19/dbhome_1"),
    )
    collector = DBPatchCollector(runner=None)
    collector.collect_host(inv, FakeHost(), command_executor=fake_executor)
    # opatch runs once per distinct home: 1 db home + 1 grid home.
    assert sorted(calls) == sorted({"/u01/app/oracle/product/19/dbhome_1", "/u01/app/19/grid"})


def test_collect_host_records_no_patches_success() -> None:
    def fake_executor(oracle_home, owner, command):
        return _result("There are no Interim patches installed in this Oracle Home.\n")

    collector = DBPatchCollector(runner=None)
    records = collector.collect_host(
        _inventory_record(grid_home=""), FakeHost(), command_executor=fake_executor
    )
    assert len(records) == 1
    assert records[0].collection_status == "success"
    assert records[0].collection_error == "no_interim_patches"
    assert records[0].patch_count == 0


def test_collect_host_records_failure() -> None:
    def fake_executor(oracle_home, owner, command):
        return _result(stderr="sudo: a password is required", returncode=1)

    collector = DBPatchCollector(runner=None)
    records = collector.collect_host(
        _inventory_record(grid_home=""), FakeHost(), command_executor=fake_executor
    )
    assert records[0].collection_status == "failed"
    assert records[0].error_category == "SUDO_DENIED"
    assert "NOPASSWD" in records[0].collection_error


def test_collect_host_disabled() -> None:
    collector = DBPatchCollector(runner=None)
    assert collector.collect_host(_inventory_record(), FakeHost(), enabled=False) == []


def test_collect_host_can_skip_grid_home() -> None:
    def fake_executor(oracle_home, owner, command):
        return _result(SAMPLE_LSPATCHES)

    collector = DBPatchCollector(runner=None)
    records = collector.collect_host(
        _inventory_record(), FakeHost(), include_grid_home=False, command_executor=fake_executor
    )
    assert {r.HOME_TYPE for r in records} == {"db"}


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def test_write_patch_inventory_outputs(tmp_path: Path) -> None:
    def fake_executor(oracle_home, owner, command):
        return _result(SAMPLE_LSPATCHES)

    collector = DBPatchCollector(runner=None)
    records = collector.collect_host(
        _inventory_record(grid_home=""), FakeHost(), command_executor=fake_executor
    )
    csv_path = write_db_patch_inventory_csv(records, tmp_path)
    json_path = write_db_patch_inventory_json(records, tmp_path)
    assert csv_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload[0]["PATCH_ID"] == "37499406"
    assert set(payload[0].keys()) == set(DB_PATCH_COLUMNS)
