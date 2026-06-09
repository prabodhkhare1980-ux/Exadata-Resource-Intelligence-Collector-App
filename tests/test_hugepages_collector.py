import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.hugepages_collector import (
    HugePagesRecord,
    parse_hugepages_output,
)
from reports.writers import write_hugepages_csv, write_hugepages_json

NORMAL = """MemTotal:        1433305088 kB
HugePages_Total:    355840
HugePages_Free:     269126
HugePages_Rsvd:          1
HugePages_Surp:          0
Hugepagesize:         2048 kB
Hugetlb:        728760320 kB
---THP---
always [madvise] never
"""

WITHOUT_THP_SECTION = """MemTotal:        16777216 kB
HugePages_Total:    100
HugePages_Free:      8
HugePages_Rsvd:      4
HugePages_Surp:      1
Hugepagesize:     2048 kB
"""


def test_parse_hugepages_normal_output() -> None:
    row = parse_hugepages_output("c1", "h1", "10.0.0.1", "now", NORMAL)
    assert row.mem_total_gb == 1367
    assert row.hp_size_kb == 2048
    assert row.hp_total == 355840
    assert row.hp_free == 269126
    assert row.hp_rsvd == 1
    assert row.hp_surp == 0
    assert row.hp_used == 86714
    assert row.hp_used_gb == 169
    assert row.hp_total_gb == 695
    assert row.hp_pct_of_memtotal == 50.8
    assert row.thp_status == "always [madvise] never"
    assert row.collection_status == "success"


def test_parse_hugepages_missing_thp_returns_unknown() -> None:
    row = parse_hugepages_output("c1", "h1", "10.0.0.1", "now", WITHOUT_THP_SECTION)
    assert row.thp_status == "UNKNOWN"
    # Sanity: still parses meminfo block fully.
    assert row.hp_total == 100
    assert row.hp_used == 92


def test_parse_hugepages_handles_divide_by_zero() -> None:
    row = parse_hugepages_output(
        "c1", "h1", "10.0.0.1", "now", "HugePages_Total: 0\nHugePages_Free: 0\nMemTotal: 0 kB\n"
    )
    assert row.hp_total == 0
    assert row.hp_used_gb == 0
    assert row.hp_total_gb == 0
    assert row.hp_pct_of_memtotal == 0.0
    assert row.hugepages_used_pct == 0.0
    assert row.hugepages_free_pct == 0.0


def test_parse_hugepages_warning_logic() -> None:
    critical = parse_hugepages_output(
        "c", "h", "a", "now", "HugePages_Total: 100\nHugePages_Free: 4\n"
    )
    warning = parse_hugepages_output(
        "c", "h", "a", "now", "HugePages_Total: 100\nHugePages_Free: 18\n"
    )
    ok = parse_hugepages_output(
        "c", "h", "a", "now", "HugePages_Total: 100\nHugePages_Free: 25\n"
    )
    assert critical.warning_level == "CRITICAL"
    assert warning.warning_level == "WARNING"
    assert ok.warning_level == "OK"


def test_hugepages_record_to_csv_row_has_analytics_columns() -> None:
    record = parse_hugepages_output("c1", "h1", "a1", "2026-03-04 16:50:48", NORMAL)
    row = record.to_csv_row()
    assert row["Cluster"] == "c1"
    assert row["Host"] == "h1"
    assert row["MemTotal"] == 1367
    assert row["HP_Size_KB"] == 2048
    assert row["HP_Total"] == 355840
    assert row["HP_Free"] == 269126
    assert row["HP_Rsvd"] == 1
    assert row["HP_Surp"] == 0
    assert row["HP_Used"] == 86714
    assert row["HP_Used_GB"] == 169
    assert row["HP_Total_GB"] == 695
    assert row["HP_Pct_of_MemTotal"] == 50.8
    assert row["THP_Status"] == "always [madvise] never"
    assert row["Timestamp"] == "2026-03-04 16:50:48"


def test_hugepages_csv_json_output_exists(tmp_path: Path) -> None:
    record = parse_hugepages_output(
        "iad1px01v1-gngym1",
        "iad1px01v1-gngym1",
        "10.0.0.1",
        "2026-03-04 16:50:48",
        NORMAL,
    )
    write_hugepages_csv([record], tmp_path)
    write_hugepages_json([record], tmp_path)
    assert (tmp_path / "hugepages.csv").exists()
    assert (tmp_path / "hugepages.json").exists()
    csv_row = list(csv.DictReader((tmp_path / "hugepages.csv").open(encoding="utf-8")))[0]
    assert csv_row["Cluster"] == "iad1px01v1-gngym1"
    assert csv_row["MemTotal"] == "1367"
    assert csv_row["HP_Total_GB"] == "695"
    assert csv_row["THP_Status"] == "always [madvise] never"
    json_row = json.loads((tmp_path / "hugepages.json").read_text(encoding="utf-8"))[0]
    assert json_row["Host"] == "iad1px01v1-gngym1"
    assert json_row["HP_Pct_of_MemTotal"] == 50.8


def test_failure_record_serializes_default_zero_fields() -> None:
    record = HugePagesRecord(
        cluster="c",
        host="h",
        address="a",
        collected_at="now",
        warning_level="ERROR",
        collection_status="failed",
        collection_error="boom",
    )
    row = record.to_csv_row()
    assert row["MemTotal"] == 0
    assert row["HP_Total"] == 0
    assert row["THP_Status"] == "UNKNOWN"
