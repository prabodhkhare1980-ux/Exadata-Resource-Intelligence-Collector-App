import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.hugepages_collector import HugePagesRecord, parse_hugepages_output
from reports.writers import write_hugepages_csv, write_hugepages_json

NORMAL = """HugePages_Total:    100
HugePages_Free:      8
HugePages_Rsvd:      4
HugePages_Surp:      1
Hugepagesize:     2048 kB
Hugetlb:        204800 kB
"""


def test_parse_hugepages_normal_output() -> None:
    row = parse_hugepages_output("c1", "h1", "10.0.0.1", "now", NORMAL)
    assert row.hugepages_total == 100
    assert row.hugepages_free == 8
    assert row.hugepages_rsvd == 4
    assert row.hugepages_surp == 1
    assert row.hugepagesize_kb == 2048
    assert row.hugetlb_kb == 204800
    assert row.hugepages_used == 92
    assert row.hugepages_used_pct == 92.0
    assert row.hugepages_free_pct == 8.0
    assert row.warning_level == "WARNING"
    assert row.collection_status == "success"


def test_parse_hugepages_zero_output() -> None:
    row = parse_hugepages_output("c1", "h1", "10.0.0.1", "now", "HugePages_Total: 0\nHugePages_Free: 0\n")
    assert row.hugepages_total == 0
    assert row.hugepages_used_pct == 0.0
    assert row.hugepages_free_pct == 0.0
    assert row.warning_level == "INFO"


def test_hugepages_warning_logic() -> None:
    critical = parse_hugepages_output("c", "h", "a", "now", "HugePages_Total: 100\nHugePages_Free: 5\n")
    warning = parse_hugepages_output("c", "h", "a", "now", "HugePages_Total: 100\nHugePages_Free: 10\n")
    ok = parse_hugepages_output("c", "h", "a", "now", "HugePages_Total: 100\nHugePages_Free: 11\n")
    assert critical.warning_level == "CRITICAL"
    assert warning.warning_level == "WARNING"
    assert ok.warning_level == "OK"


def test_hugepages_csv_json_output_exists(tmp_path: Path) -> None:
    record = HugePagesRecord(cluster="c", host="h", address="a", collected_at="now", hugepages_total=1, collection_status="success")
    write_hugepages_csv([record], tmp_path)
    write_hugepages_json([record], tmp_path)
    assert (tmp_path / "hugepages.csv").exists()
    assert (tmp_path / "hugepages.json").exists()
    assert list(csv.DictReader((tmp_path / "hugepages.csv").open(encoding="utf-8")))[0]["cluster"] == "c"
    assert json.loads((tmp_path / "hugepages.json").read_text(encoding="utf-8"))[0]["host"] == "h"
