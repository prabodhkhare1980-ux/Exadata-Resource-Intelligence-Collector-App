import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.asm_diskgroups_collector import ASMDiskgroupRecord, _build_diskgroup_record
from reports.writers import write_asm_diskgroups_json, write_asm_summary_csv, write_asm_summary_json


def _context() -> dict[str, str]:
    return {
        "collected_at": "2026-06-03T00:00:00+00:00",
        "asm_collection_status": "success",
        "grid_home": "/u01/grid",
        "grid_owner": "grid",
        "asm_sid": "+ASM1",
        "asmcmd_path": "/u01/grid/bin/asmcmd",
        "asm_command": "sudo -n -u grid asmcmd lsdg",
        "asm_env_stdout": "raw env",
        "asm_returncode": "0",
        "asmcmd_stdout": "raw stdout",
        "asmcmd_stderr": "raw stderr",
        "sqlplus_stdout": "raw sql stdout",
        "sqlplus_stderr": "raw sql stderr",
        "sqlplus_returncode": "0",
    }


def test_asm_summary_deduplicates_cluster_diskgroup_and_calculates_tb(tmp_path: Path) -> None:
    first = _build_diskgroup_record("c1", "h1", "10.0.0.1", "DATA", "MOUNTED", "EXTERN", 2 * 1024 * 1024, 1024 * 1024, 512 * 1024, _context())
    duplicate = _build_diskgroup_record("c1", "h2", "10.0.0.2", "DATA", "MOUNTED", "EXTERN", 999, 111, 22, _context())
    reco = _build_diskgroup_record("c1", "h1", "10.0.0.1", "RECO", "MOUNTED", "HIGH", 3 * 1024 * 1024, 1024 * 1024, 256 * 1024, _context())
    assert first and duplicate and reco

    write_asm_summary_csv([first, duplicate, reco], tmp_path)
    write_asm_summary_json([first, duplicate, reco], tmp_path)

    rows = list(csv.DictReader((tmp_path / "asm_summary.csv").open(encoding="utf-8")))
    assert [(row["cluster"], row["diskgroup_name"]) for row in rows] == [("c1", "DATA"), ("c1", "RECO")]
    assert rows[0]["sample_host"] == "h1"
    assert rows[0]["total_tb"] == "2.0"
    assert rows[0]["free_tb"] == "1.0"
    assert rows[0]["usable_tb"] == "0.5"
    assert json.loads((tmp_path / "asm_summary.json").read_text(encoding="utf-8"))[0]["diskgroup_name"] == "DATA"


def test_asm_debug_fields_hidden_by_default_and_available_when_enabled(tmp_path: Path) -> None:
    record = _build_diskgroup_record("c1", "h1", "10.0.0.1", "DATA", "MOUNTED", "EXTERN", 100, 20, 10, _context())
    assert record

    write_asm_diskgroups_json([record], tmp_path)
    row = json.loads((tmp_path / "asm_diskgroups.json").read_text(encoding="utf-8"))[0]
    assert "asm_command" not in row
    assert "asmcmd_stdout" not in row
    assert row["total_tb"] == 0.0

    write_asm_diskgroups_json([record], tmp_path, include_debug=True)
    debug_row = json.loads((tmp_path / "asm_diskgroups.json").read_text(encoding="utf-8"))[0]
    assert debug_row["asm_command"] == "sudo -n -u grid asmcmd lsdg"
    assert "asmcmd_stdout" in debug_row


def test_asm_warning_levels() -> None:
    ok = _build_diskgroup_record("c", "h", "a", "OKDG", "MOUNTED", "EXTERN", 100, 16, 10, _context())
    warning = _build_diskgroup_record("c", "h", "a", "WARNDG", "MOUNTED", "EXTERN", 100, 15, 10, _context())
    critical = _build_diskgroup_record("c", "h", "a", "CRITDG", "MOUNTED", "EXTERN", 100, 5, 1, _context())
    assert ok and warning and critical
    assert ok.warning_level == "OK"
    assert warning.warning_level == "WARNING"
    assert critical.warning_level == "CRITICAL"
