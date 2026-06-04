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
    write_health_summary_html,
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
        "recommendation": "Review DB SGA/HugePages allocation; risk of HugePages exhaustion.",
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
    assert any(
        row["category"] == "FILESYSTEM"
        and row["object_name"] == "/"
        and row["warning_level"] == "CRITICAL"
        and row["recommendation"] == "Immediate cleanup or expansion required."
        for row in rows
    )
    assert any(row["category"] == "DB_INVENTORY" and row["object_name"] == "DB1" and row["warning_level"] == "OK" for row in rows)
    assert health_summary_counts(rows) == {"CRITICAL": 2, "WARNING": 0, "OK": 2}

    csv_path = write_health_summary_csv([os_record], [asm_record], [hugepages_record], [db_record], tmp_path)
    json_path = write_health_summary_json([os_record], [asm_record], [hugepages_record], [db_record], tmp_path)
    html_path = write_health_summary_html([os_record], [asm_record], [hugepages_record], [db_record], tmp_path)

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
        "recommendation",
        "details",
        "collected_at",
    }
    assert json.loads(json_path.read_text(encoding="utf-8")) == rows
    html = html_path.read_text(encoding="utf-8")
    assert "<th>recommendation</th>" in html
    assert "Immediate cleanup or expansion required." in html
    assert "Review DB SGA/HugePages allocation; risk of HugePages exhaustion." in html
    assert '<tr class="critical">' in html


def test_health_summary_recommendation_boundary_levels() -> None:
    warning_record = OSCollectionRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="now",
        status="ok",
        filesystems=[{"use_percent": "85%", "mounted_on": "/u01"}],
    )
    warning_hugepages = HugePagesRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="now",
        hugepages_total=100,
        hugepages_free=10,
        hugepages_used=90,
        hugepages_used_pct=90.0,
        hugepages_free_pct=10.0,
        warning_level="WARNING",
        collection_status="success",
    )

    rows = build_health_summary_rows([warning_record], [], [warning_hugepages], [])

    assert any(
        row["category"] == "FILESYSTEM"
        and row["warning_level"] == "WARNING"
        and row["recommendation"] == "Review growth and cleanup candidates."
        for row in rows
    )
    assert any(
        row["category"] == "HUGEPAGES"
        and row["warning_level"] == "WARNING"
        and row["recommendation"] == "Monitor HugePages free count."
        for row in rows
    )


def test_health_summary_includes_db_resource_status_rows() -> None:
    db_record = DBInventoryRecord(
        cluster="c1",
        host="h1",
        address="10.0.0.1",
        collected_at="2026-06-03T00:00:03+00:00",
        status="ok",
        databases=["DB1", "DB2", "DB3"],
        srvctl_status={
            "DB1": "Instance DB1 is running on node h1",
            "DB2": "Instance DB2 is not running",
            "DB3": "Instance DB3 is running on node h1",
        },
        db_resource_details=[
            {"DB_NAME": "DB1", "db_unique_name": "DB1", "collection_status": "success", "Collected_At": "now"},
            {"DB_NAME": "", "db_unique_name": "DB2", "collection_status": "skipped", "collection_error": "no_local_running_instance", "Collected_At": "now"},
            {"DB_NAME": "DB3", "db_unique_name": "DB3", "collection_status": "failed", "collection_error": "ORA-01031", "Collected_At": "now"},
        ],
    )

    rows = build_health_summary_rows([], [], [], [db_record])

    assert any(row["category"] == "DB_RESOURCE" and row["object_name"] == "DB1" and row["warning_level"] == "OK" for row in rows)
    assert any(
        row["category"] == "DB_RESOURCE"
        and row["object_name"] == "DB2"
        and row["warning_level"] == "WARNING"
        and row["recommendation"] == "No local running instance on this host."
        for row in rows
    )
    assert any(
        row["category"] == "DB_RESOURCE"
        and row["object_name"] == "DB3"
        and row["warning_level"] == "CRITICAL"
        and row["recommendation"] == "Review local SYSDBA connectivity and database open state."
        for row in rows
    )
