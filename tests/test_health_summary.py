import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.asm_diskgroups_collector import ASMDiskgroupRecord
from collectors.db_inventory_collector import DBInventoryRecord
from collectors.hugepages_collector import HugePagesRecord
from collectors.os_collector import OSCollectionRecord
from reports.writers import (
    build_health_summary_rows,
    health_summary_counts,
    write_health_summary_csv,
    write_health_summary_json,
)


def test_health_summary_merges_key_collector_results(tmp_path: Path) -> None:
    os_record = OSCollectionRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="2026-06-03T00:00:00+00:00",
        status="ok",
        filesystems=[
            {
                "filesystem": "/dev/mapper/root",
                "type": "xfs",
                "size": "100G",
                "used": "97G",
                "available": "3G",
                "use_percent": "97%",
                "mounted_on": "/",
            }
        ],
    )
    asm_record = ASMDiskgroupRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="2026-06-03T00:00:01+00:00",
        diskgroup_name="DATAC1",
        state="MOUNTED",
        type="NORMAL",
        used_pct=58.79,
        free_pct=41.21,
        usable_pct=40.0,
        warning_level="OK",
        asm_collection_status="success",
    )
    hugepages_record = HugePagesRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="2026-06-03T00:00:02+00:00",
        hugepages_total=100,
        hugepages_free=2,
        hugepages_used=98,
        hugepages_used_pct=97.84,
        hugepages_free_pct=2.16,
        warning_level="CRITICAL",
        collection_status="success",
    )
    db_record = DBInventoryRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="2026-06-03T00:00:03+00:00",
        status="ok",
        databases=["DB1"],
        srvctl_status={"DB1": "Instance DB1 is running on node h1"},
    )

    rows = build_health_summary_rows([os_record], [asm_record], [hugepages_record], [db_record])

    assert {
        "cluster": "c1",
        "host": "h1",
        "category": "HUGEPAGES",
        "object_name": "host",
        "metric": "free_pct",
        "value": 2.16,
        "warning_level": "CRITICAL",
        "details": json.dumps(
            {
                "collection_status": "success",
                "free": 2,
                "total": 100,
                "used": 98,
                "used_pct": 97.84,
            },
            sort_keys=True,
        ),
        "collected_at": "2026-06-03T00:00:02+00:00",
    } in rows
    assert any(row["category"] == "ASM" and row["object_name"] == "DATAC1" and row["value"] == 58.79 for row in rows)
    assert any(row["category"] == "FILESYSTEM" and row["object_name"] == "/" and row["warning_level"] == "CRITICAL" for row in rows)
    assert any(row["category"] == "DB_INVENTORY" and row["object_name"] == "DB1" and row["warning_level"] == "OK" for row in rows)
    assert health_summary_counts(rows) == {"CRITICAL": 2, "WARNING": 0, "OK": 2}

    csv_path = write_health_summary_csv([os_record], [asm_record], [hugepages_record], [db_record], tmp_path)
    json_path = write_health_summary_json([os_record], [asm_record], [hugepages_record], [db_record], tmp_path)

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        csv_rows = list(csv.DictReader(csv_file))
    assert csv_rows[0].keys() == {
        "cluster",
        "host",
        "category",
        "object_name",
        "metric",
        "value",
        "warning_level",
        "details",
        "collected_at",
    }
    assert json.loads(json_path.read_text(encoding="utf-8")) == rows
