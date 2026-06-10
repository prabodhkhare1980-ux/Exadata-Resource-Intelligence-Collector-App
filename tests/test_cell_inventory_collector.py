"""Tests for the Exadata storage-cell inventory collector (dcli + cellcli)."""

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from collectors.cell_inventory_collector import (
    CELL_INVENTORY_COLUMNS,
    CellInventoryCollector,
    build_dcli_cellcli_command,
    parse_cell_size_gb,
    parse_dcli_detail,
    parse_dcli_detail_multi,
)
from reports.writers import write_cell_inventory_csv, write_cell_inventory_json
from ssh_runner import CommandResult


class FakeHost:
    name = "db01"
    address = "db01.example.com"
    force_tty = False
    environment = "onprem"


class FakeCluster:
    name = "rac01"


def _result(stdout: str = "", stderr: str = "", returncode: int = 0, timed_out: bool = False) -> CommandResult:
    return CommandResult(FakeHost(), [], stdout, stderr, returncode, timed_out)


CELL_DETAIL = """cel01: name:           cel01
cel01: cellVersion:        OSS_23.1.0.0.0_LINUX.X64_240101
cel01: makeModel:          Oracle Corporation SUN SERVER X9-2L High Capacity
cel01: status:             online
cel01: cpuCount:           32
cel02: name:           cel02
cel02: cellVersion:        OSS_23.1.0.0.0_LINUX.X64_240101
cel02: makeModel:          Oracle Corporation SUN SERVER X9-2L High Capacity
cel02: status:             online
cel02: cpuCount:           32
"""

FLASHCACHE_DETAIL = """cel01: name:           cel01_FLASHCACHE
cel01: size:               5.82105T
cel01: status:             normal
cel02: name:           cel02_FLASHCACHE
cel02: size:               5.82105T
cel02: status:             normal
"""

PHYSICALDISK_DETAIL = """cel01: name:           20:0
cel01: physicalSize:       10T
cel01: diskType:           HardDisk
cel01: name:           20:1
cel01: physicalSize:       10T
cel01: diskType:           HardDisk
cel01: name:           FLASH_1_1
cel01: physicalSize:       6.4T
cel01: diskType:           FlashDisk
"""


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------


def test_build_dcli_command() -> None:
    cmd = build_dcli_cellcli_command("/opt/cells/cell_group", "celladmin", "list cell detail", 60)
    assert "dcli -g /opt/cells/cell_group -l celladmin" in cmd
    assert "cellcli -e list cell detail" in cmd
    assert "timeout 60s" in cmd


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_dcli_detail_groups_by_cell() -> None:
    parsed = parse_dcli_detail(CELL_DETAIL)
    assert set(parsed) == {"cel01", "cel02"}
    assert parsed["cel01"]["cellVersion"].startswith("OSS_23.1")
    # makeModel keeps spaces intact.
    assert parsed["cel01"]["makeModel"] == "Oracle Corporation SUN SERVER X9-2L High Capacity"
    assert parsed["cel01"]["cpuCount"] == "32"


def test_parse_dcli_detail_multi_splits_objects_on_name() -> None:
    parsed = parse_dcli_detail_multi(PHYSICALDISK_DETAIL)
    assert len(parsed["cel01"]) == 3
    assert parsed["cel01"][0]["physicalSize"] == "10T"
    assert parsed["cel01"][2]["diskType"] == "FlashDisk"


def test_parse_cell_size_gb_units() -> None:
    assert parse_cell_size_gb("5.82105T") == round(5.82105 * 1024, 2)
    assert parse_cell_size_gb("745.211G") == 745.21
    assert parse_cell_size_gb("100M") == round(100 / 1024, 2)
    assert parse_cell_size_gb("10TB") == round(10 * 1024, 2)  # trailing B tolerated
    assert parse_cell_size_gb("") is None
    assert parse_cell_size_gb("garbage") is None


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


def test_collect_cluster_merges_cell_flash_and_disk() -> None:
    def fake_executor(kind, command):
        return {
            "cell": _result(CELL_DETAIL),
            "flashcache": _result(FLASHCACHE_DETAIL),
            "physicaldisk": _result(PHYSICALDISK_DETAIL),
        }[kind]

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), command_executor=fake_executor
    )
    assert len(records) == 2
    cel01 = next(r for r in records if r.CELL_NAME == "cel01")
    assert cel01.CELL_VERSION.startswith("OSS_23.1")
    assert cel01.MAKE_MODEL.endswith("High Capacity")
    assert cel01.STATUS == "online"
    assert cel01.CPU_COUNT == "32"
    # Flash cache 5.82105 T -> GB
    assert float(cel01.FLASH_CACHE_GB) == round(5.82105 * 1024, 2)
    # 2 x 10T hard disks summed.
    assert float(cel01.HARD_DISK_GB) == round(20 * 1024, 2)
    # 1 x 6.4T flash disk.
    assert float(cel01.FLASH_DISK_GB) == round(6.4 * 1024, 2)
    assert cel01.collection_status == "success"


def test_collect_cluster_tolerates_missing_flash_and_disk() -> None:
    def fake_executor(kind, command):
        if kind == "cell":
            return _result(CELL_DETAIL)
        return _result(stderr="cellcli: object not found", returncode=1)

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), command_executor=fake_executor
    )
    assert len(records) == 2
    # Cell list still parsed; flash/disk fields just blank.
    assert all(r.collection_status == "success" for r in records)
    assert records[0].FLASH_CACHE_GB == ""


def test_collect_cluster_records_dcli_failure() -> None:
    def fake_executor(kind, command):
        return _result(stderr="dcli: command not found", returncode=127)

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), command_executor=fake_executor
    )
    assert len(records) == 1
    assert records[0].collection_status == "failed"
    assert records[0].error_category == "DCLI_NOT_FOUND"


def test_collect_cluster_disabled() -> None:
    collector = CellInventoryCollector(runner=None)
    assert collector.collect_cluster(FakeCluster(), FakeHost(), enabled=False) == []


def test_collect_cluster_empty_output() -> None:
    def fake_executor(kind, command):
        return _result("")  # ran but nothing parsed

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), command_executor=fake_executor
    )
    assert records[0].collection_status == "failed"
    assert records[0].error_category == "EMPTY_OUTPUT"


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def test_write_cell_inventory_outputs(tmp_path: Path) -> None:
    def fake_executor(kind, command):
        return {
            "cell": _result(CELL_DETAIL),
            "flashcache": _result(FLASHCACHE_DETAIL),
            "physicaldisk": _result(PHYSICALDISK_DETAIL),
        }[kind]

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), command_executor=fake_executor
    )
    csv_path = write_cell_inventory_csv(records, tmp_path)
    json_path = write_cell_inventory_json(records, tmp_path)
    assert csv_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload[0]["CELL_NAME"] == "cel01"
    assert set(payload[0].keys()) == set(CELL_INVENTORY_COLUMNS)
