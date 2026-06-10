"""Tests for the newly added Dash normalizers (Tier 1 wiring).

These cover the helpers that surface previously-unused collector
outputs: OS meminfo/lscpu parsing, DB resource details, the DB memory
cluster rollup, and the version inventory drift indicator.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.normalizers import (  # noqa: E402
    build_cluster_version_drift,
    build_os_cpu_table,
    build_os_memory_table,
    normalize_db_memory_cluster_summary,
    normalize_db_resource_details,
    normalize_version_inventory,
    parse_meminfo,
)


# ---------------------------------------------------------------------------
# OS memory
# ---------------------------------------------------------------------------


def test_parse_meminfo_accepts_json_string() -> None:
    sample = {"MemTotal": "16777216 kB", "MemFree": "8388608 kB"}
    parsed = parse_meminfo(json.dumps(sample))
    assert parsed["MemTotal"] == "16777216 kB"
    assert parsed["MemFree"] == "8388608 kB"


def test_parse_meminfo_accepts_text_blob() -> None:
    text = "MemTotal: 16777216 kB\nMemFree: 8388608 kB\n"
    parsed = parse_meminfo(text)
    assert parsed["MemTotal"] == "16777216 kB"
    assert parsed["MemFree"] == "8388608 kB"


def test_build_os_memory_table_computes_gb_used_pct_and_severity() -> None:
    inventory = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host": "h1",
                "hostname": "h1",
                "status": "ok",
                "meminfo_json": json.dumps(
                    {
                        "MemTotal": "33554432 kB",  # 32 GB
                        "MemFree": "4194304 kB",
                        "MemAvailable": "16777216 kB",  # 16 GB
                        "SwapTotal": "8388608 kB",  # 8 GB
                        "SwapFree": "8388608 kB",
                    }
                ),
            }
        ]
    )
    table = build_os_memory_table(inventory)
    assert len(table) == 1
    row = table.iloc[0]
    assert row["mem_total_gb"] == pytest.approx(32.0)
    assert row["mem_available_gb"] == pytest.approx(16.0)
    assert row["mem_used_gb"] == pytest.approx(16.0)
    # Used = (32 - 16) / 32 = 50%
    assert row["mem_used_pct"] == pytest.approx(50.0)
    # Swap is unused.
    assert row["swap_used_gb"] == pytest.approx(0.0)
    assert row["swap_used_pct"] == pytest.approx(0.0)
    # 50% used is below the WARNING threshold.
    assert row["severity"] == "OK"


def test_build_os_memory_table_handles_empty() -> None:
    table = build_os_memory_table(pd.DataFrame())
    assert table.empty
    assert "mem_total_gb" in table.columns


# ---------------------------------------------------------------------------
# OS CPU
# ---------------------------------------------------------------------------


def test_build_os_cpu_table_parses_lscpu_json() -> None:
    inventory = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host": "h1",
                "hostname": "h1",
                "status": "ok",
                "cpu_json": json.dumps(
                    {
                        "CPU(s)": "64",
                        "Core(s) per socket": "16",
                        "Socket(s)": "2",
                        "Thread(s) per core": "2",
                        "Model name": "Intel(R) Xeon(R) Gold 6248",
                    }
                ),
                "uptime": "up 42 days",
            }
        ]
    )
    table = build_os_cpu_table(inventory)
    row = table.iloc[0]
    assert row["cpus"] == 64
    assert row["cores_per_socket"] == 16
    assert row["sockets"] == 2
    assert row["threads_per_core"] == 2
    assert row["physical_cores"] == 32
    assert "Xeon" in row["cpu_model"]


def test_build_os_cpu_table_handles_missing_cpu_json() -> None:
    inventory = pd.DataFrame(
        [{"cluster": "c1", "host": "h1", "hostname": "h1", "status": "ok"}]
    )
    table = build_os_cpu_table(inventory)
    assert len(table) == 1
    assert pd.isna(table.iloc[0]["physical_cores"])


# ---------------------------------------------------------------------------
# DB resource details
# ---------------------------------------------------------------------------


def test_normalize_db_resource_details_renames_csv_columns() -> None:
    raw = pd.DataFrame(
        [
            {
                "Cluster": "c1",
                "HOST_NAME": "h1",
                "DB_NAME": "ORCL",
                "DB_ROLE": "PRIMARY",
                "OPEN_MODE": "READ WRITE",
                "VERSION": "19.0.0.0.0",
                "RAC_ENABLED": "YES",
                "INST_COUNT": 2,
                "SGA_TARGET_GB": 32.0,
                "SGA_MAX_SIZE_GB": 40.0,
                "PGA_AGGR_TARGET_GB": 16.0,
                "PGA_AGGR_LIMIT_GB": 24.0,
                "PROCESSES": 600,
                "CPU_COUNT": 32,
                "DB_SIZE_GB": 1000.0,
                "USED_DB_SIZE_GB": 850.0,
                "db_unique_name": "ORCL",
            }
        ]
    )
    table = normalize_db_resource_details(raw)
    row = table.iloc[0]
    assert row["cluster"] == "c1"
    assert row["db_name"] == "ORCL"
    assert row["sga_target_gb"] == pytest.approx(32.0)
    assert row["db_used_pct"] == pytest.approx(85.0)  # derived
    assert row["warning_level"] == "WARNING"  # 85% is WARNING by default thresholds


def test_normalize_db_resource_details_preserves_json_snake_case() -> None:
    raw = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host_name": "h1",
                "db_name": "PROD",
                "cpu_count": 64,
                "db_size_gb": 2000.0,
                "used_db_size_gb": 1900.0,
                "db_used_pct": 95.0,
            }
        ]
    )
    table = normalize_db_resource_details(raw)
    row = table.iloc[0]
    assert row["cpu_count"] == 64
    assert row["db_used_pct"] == pytest.approx(95.0)
    assert row["warning_level"] == "CRITICAL"


def test_normalize_db_resource_details_handles_empty() -> None:
    table = normalize_db_resource_details(pd.DataFrame())
    assert table.empty
    assert "db_used_pct" in table.columns


# ---------------------------------------------------------------------------
# DB memory cluster summary
# ---------------------------------------------------------------------------


def test_normalize_db_memory_cluster_summary_renames_and_coerces() -> None:
    raw = pd.DataFrame(
        [
            {
                "Cluster": "c1",
                "database_count": "5",
                "instance_count": "10",
                "avg_sga_used_gb": "32.5",
                "max_sga_used_gb": "48.0",
                "total_latest_sga_used_gb": "160",
                "total_latest_pga_used_gb": "32",
                "total_latest_pga_allocated_gb": "40",
            }
        ]
    )
    table = normalize_db_memory_cluster_summary(raw)
    row = table.iloc[0]
    assert row["cluster"] == "c1"
    assert row["database_count"] == 5
    assert row["instance_count"] == 10
    assert row["max_sga_used_gb"] == pytest.approx(48.0)
    assert row["total_latest_sga_used_gb"] == pytest.approx(160.0)


def test_normalize_db_memory_cluster_summary_handles_empty() -> None:
    table = normalize_db_memory_cluster_summary(pd.DataFrame())
    assert table.empty
    assert "total_latest_sga_used_gb" in table.columns


# ---------------------------------------------------------------------------
# Version inventory + cluster drift
# ---------------------------------------------------------------------------


def _version_row(
    cluster: str, host: str, image_version: str, gi_patch: str
) -> dict[str, object]:
    return {
        "cluster": cluster,
        "host": host,
        "address": f"{host}.example.com",
        "node_type": "COMPUTE",
        "image_version": image_version,
        "exadata_software_version": image_version,
        "image_status": "success",
        "image_activated": "2025-01-01",
        "kernel_version": "5.4.0",
        "gi_active_version": "19.0.0.0.0",
        "gi_release_version": "19.0.0.0.0",
        "gi_release_patch_string": gi_patch,
        "gi_release_patch_level": "DBRU_2025_Q1",
        "collection_status": "success",
        "collected_at": "2026-06-10T00:00:00Z",
    }


def test_normalize_version_inventory_returns_stable_columns() -> None:
    raw = pd.DataFrame([_version_row("c1", "h1", "23.1.0.0", "PATCH_A")])
    table = normalize_version_inventory(raw)
    assert list(table.columns)[:4] == ["cluster", "host", "address", "node_type"]
    assert table.iloc[0]["image_version"] == "23.1.0.0"


def test_build_cluster_version_drift_flags_drift() -> None:
    raw = pd.DataFrame(
        [
            _version_row("c1", "h1", "23.1.0.0", "PATCH_A"),
            _version_row("c1", "h2", "23.1.1.0", "PATCH_A"),  # image drift
            _version_row("c2", "h3", "23.1.0.0", "PATCH_A"),
            _version_row("c2", "h4", "23.1.0.0", "PATCH_A"),  # no drift
        ]
    )
    drift = build_cluster_version_drift(raw)
    drift = drift.set_index("cluster")
    assert bool(drift.loc["c1", "image_drift"]) is True
    assert bool(drift.loc["c1", "gi_patch_drift"]) is False
    assert drift.loc["c1", "severity"] == "WARNING"
    assert bool(drift.loc["c2", "image_drift"]) is False
    assert drift.loc["c2", "severity"] == "OK"


def test_build_cluster_version_drift_handles_empty() -> None:
    drift = build_cluster_version_drift(pd.DataFrame())
    assert drift.empty
    assert "image_drift" in drift.columns


# ---------------------------------------------------------------------------
# Cell inventory
# ---------------------------------------------------------------------------


def test_normalize_cell_inventory_derives_tb_columns() -> None:
    from services.normalizers import normalize_cell_inventory

    raw = pd.DataFrame([
        {
            "Cluster": "rac01", "source_host": "db01", "CELL_NAME": "cel01",
            "CELL_VERSION": "OSS_23.1.0.0.0", "CELL_RELEASE_VERSION": "23.1.0.0.0",
            "MAKE_MODEL": "X9-2L HC", "STATUS": "online", "CPU_COUNT": "32",
            "FLASH_CACHE_GB": "5963", "FLASH_CACHE_MODE": "WriteBack",
            "HARD_DISK_GB": "20480", "FLASH_DISK_GB": "6553",
            "HARD_DISK_COUNT": "12", "FLASH_DISK_COUNT": "4",
            "cell_access_method": "exacli", "cell_target": "192.168.136.5",
        }
    ])
    table = normalize_cell_inventory(raw)
    row = table.iloc[0]
    assert row["cluster"] == "rac01"
    assert row["cell_release_version"] == "23.1.0.0.0"
    assert row["flash_cache_tb"] == pytest.approx(5963 / 1024, abs=0.01)
    assert row["hard_disk_tb"] == pytest.approx(20480 / 1024, abs=0.01)
    assert row["cell_access_method"] == "exacli"


def test_normalize_cell_inventory_handles_empty() -> None:
    from services.normalizers import normalize_cell_inventory

    table = normalize_cell_inventory(pd.DataFrame())
    assert table.empty
    assert "flash_cache_tb" in table.columns


def test_normalize_cell_inventory_errors() -> None:
    from services.normalizers import normalize_cell_inventory_errors

    raw = pd.DataFrame([
        {
            "Cluster": "rac02", "source_host": "db03", "cell_access_method": "dcli",
            "cell_target": "cel09", "cell_user_attempted": "celladmin,root",
            "error_category": "CELL_AUTH", "collection_error": "Permission denied",
            "dcli_available": "true", "cell_group_file_used": "/root/cell_group",
            "cell_hosts_discovered": "cel09",
        }
    ])
    table = normalize_cell_inventory_errors(raw)
    row = table.iloc[0]
    assert row["error_category"] == "CELL_AUTH"
    assert row["warning_level"] == "CRITICAL"
