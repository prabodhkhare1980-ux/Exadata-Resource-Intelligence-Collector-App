import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collectors.version_inventory_collector import (
    VersionInventoryRecord,
    parse_imageinfo,
    parse_release_patch,
    parse_version_inventory_sections,
)
from reports.writers import build_health_summary_rows, write_version_inventory_csv, write_version_inventory_json

IMAGEINFO = """Kernel version: 5.15.0-308.179.6.16.el8uek.x86_64
Uptrack kernel version: 5.15.0-316.196.4.1.el8uek.x86_64
Image kernel version: 5.15.0-308.179.6.16.el8uek
Image version: 25.2.7.0.0.260226
Image activated: 2026-03-16 16:25:44 -0400
Image status: success
Exadata software version: 25.2.7.0.0.260226
Node type: GUEST
System partition on device: /dev/mapper/VGExaDb-LVDbSys1
"""

RELEASEPATCH = """Oracle Clusterware release patch level is [2530752274] and the complete list of patches [35221462 37537949 38743669 38743682 38743688 38743695 38743706 ] have been applied on the local node. The release patch string is [23.26.1.0.0]."""


def test_parse_imageinfo_key_values_cleanly() -> None:
    parsed = parse_imageinfo(IMAGEINFO)

    assert parsed["image_version"] == "25.2.7.0.0.260226"
    assert parsed["exadata_software_version"] == "25.2.7.0.0.260226"
    assert parsed["image_activated"] == "2026-03-16 16:25:44 -0400"
    assert parsed["image_status"] == "success"
    assert parsed["system_partition_on_device"] == "/dev/mapper/VGExaDb-LVDbSys1"


def test_parse_release_patch_output() -> None:
    parsed = parse_release_patch(RELEASEPATCH)

    assert parsed["level"] == "2530752274"
    assert parsed["patch_string"] == "23.26.1.0.0"
    assert parsed["patch_list"] == ["35221462", "37537949", "38743669", "38743682", "38743688", "38743695", "38743706"]


def test_parse_version_inventory_sections() -> None:
    record = parse_version_inventory_sections(
        "c1",
        "h1",
        "10.0.0.1",
        "now",
        {
            "imageinfo": IMAGEINFO,
            "gi_active_version": "Oracle Clusterware active version on the cluster is [23.0.0.0.0]",
            "gi_software_patch": "Oracle Clusterware software patch level is [2530752274]",
            "gi_release_version": "Oracle Clusterware release version on the cluster is [23.0.0.0.0]",
            "gi_release_patch": RELEASEPATCH,
        },
        ssh_returncode=0,
    )

    assert record.collection_status == "success"
    assert record.image_version == "25.2.7.0.0.260226"
    assert record.gi_active_version == "23.0.0.0.0"
    assert record.gi_software_patch_level == "2530752274"
    assert record.gi_release_version == "23.0.0.0.0"
    assert record.gi_release_patch_level == "2530752274"
    assert record.gi_release_patch_string == "23.26.1.0.0"
    assert record.gi_release_patch_list[-1] == "38743706"


def test_version_inventory_csv_json_output_exists(tmp_path: Path) -> None:
    record = VersionInventoryRecord(
        cluster="c",
        host="h",
        address="a",
        collected_at="now",
        collection_status="success",
        image_version="25.2.7.0.0.260226",
        image_status="success",
        gi_release_patch_string="23.26.1.0.0",
        gi_release_patch_list=["35221462"],
    )

    write_version_inventory_csv([record], tmp_path)
    write_version_inventory_json([record], tmp_path)

    assert (tmp_path / "version_inventory.csv").exists()
    assert (tmp_path / "version_inventory.json").exists()
    row = list(csv.DictReader((tmp_path / "version_inventory.csv").open(encoding="utf-8")))[0]
    assert row["image_version"] == "25.2.7.0.0.260226"
    assert json.loads(row["gi_release_patch_list"]) == ["35221462"]
    assert json.loads((tmp_path / "version_inventory.json").read_text(encoding="utf-8"))[0]["host"] == "h"


def test_version_inventory_health_warnings_for_status_and_cluster_drift() -> None:
    records = [
        VersionInventoryRecord(cluster="c1", host="h1", address="a1", collected_at="1", collection_status="success", image_status="success", image_version="25.2", gi_release_patch_string="23.26.1"),
        VersionInventoryRecord(cluster="c1", host="h2", address="a2", collected_at="2", collection_status="success", image_status="failed", image_version="25.3", gi_release_patch_string="23.26.2"),
    ]

    rows = build_health_summary_rows([], [], [], [], records)

    assert any(row["metric"] == "image_status" and row["host"] == "h2" and row["warning_level"] == "WARNING" for row in rows)
    assert any(row["metric"] == "image_version" and row["value"] == "mismatch" and row["warning_level"] == "WARNING" for row in rows)
    assert any(row["metric"] == "gi_release_patch_string" and row["value"] == "mismatch" and row["warning_level"] == "WARNING" for row in rows)
