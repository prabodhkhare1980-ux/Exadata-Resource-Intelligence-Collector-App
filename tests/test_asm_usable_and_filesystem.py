"""Tests for ASM usable-capacity math and the richer filesystem normalizer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.normalizers import (  # noqa: E402
    _asm_mirror_factor,
    build_asm_diskgroup_detail,
    build_filesystem_host_rollup,
    explode_filesystems,
    normalize_asm,
    parse_df_size_gb,
)


# ---------------------------------------------------------------------------
# ASM redundancy / usable math
# ---------------------------------------------------------------------------


def test_asm_mirror_factor_known_types() -> None:
    assert _asm_mirror_factor("HIGH") == 3.0
    assert _asm_mirror_factor("high") == 3.0
    assert _asm_mirror_factor("NORMAL") == 2.0
    assert _asm_mirror_factor("EXTERNAL") == 1.0
    assert _asm_mirror_factor("EXT") == 1.0
    assert _asm_mirror_factor("FLEX") == 2.0
    assert _asm_mirror_factor("EXTEND") == 2.0


def test_asm_mirror_factor_unknown_stays_one() -> None:
    """Unknown redundancy must not silently inflate usable space."""

    assert _asm_mirror_factor("WEIRD") == 1.0
    assert _asm_mirror_factor(None) == 1.0
    assert _asm_mirror_factor(float("nan")) == 1.0


def test_normalize_asm_derives_usable_columns_for_high_redundancy() -> None:
    """Reproduces the field screenshot: DATAC1 HIGH 519.54 raw -> 173.18 usable."""

    raw = pd.DataFrame([{
        "cluster": "onprem-dc04dx26", "host": "db01",
        "diskgroup_name": "DATAC1", "type": "HIGH",
        "total_tb": 519.54, "free_tb": 273.70, "usable_tb": 80.0,
        "used_pct": 47.3, "warning_level": "OK",
    }])
    table = normalize_asm(raw)
    row = table.iloc[0]
    # 519.54 / 3 = 173.18
    assert row["usable_total_tb"] == pytest.approx(173.18, abs=0.01)
    # raw used = 519.54 - 273.70 = 245.84; /3 = 81.95
    assert row["usable_used_tb"] == pytest.approx(81.95, abs=0.01)


def test_normalize_asm_normal_redundancy() -> None:
    raw = pd.DataFrame([{
        "cluster": "c1", "diskgroup_name": "DATA", "type": "NORMAL",
        "total_tb": 100.0, "free_tb": 40.0, "usable_tb": 20.0, "used_pct": 60.0,
        "warning_level": "OK",
    }])
    row = normalize_asm(raw).iloc[0]
    assert row["usable_total_tb"] == pytest.approx(50.0)
    assert row["usable_used_tb"] == pytest.approx(30.0)  # 60 raw used / 2


def test_normalize_asm_external_redundancy_unchanged() -> None:
    raw = pd.DataFrame([{
        "cluster": "c1", "diskgroup_name": "DATA", "type": "EXTERNAL",
        "total_tb": 100.0, "free_tb": 40.0, "usable_tb": 35.0, "used_pct": 60.0,
        "warning_level": "OK",
    }])
    row = normalize_asm(raw).iloc[0]
    assert row["usable_total_tb"] == pytest.approx(100.0)
    assert row["usable_used_tb"] == pytest.approx(60.0)


def test_build_asm_diskgroup_detail_has_both_views() -> None:
    """Detail must carry usable AND raw columns for the dashboard."""

    raw = pd.DataFrame([{
        "cluster": "onprem-dc04dx26", "diskgroup_name": "DATAC1",
        "type": "HIGH", "state": "MOUNTED",
        "total_tb": 519.54, "free_tb": 273.70, "usable_tb": 80.0,
        "used_pct": 47.3, "warning_level": "OK", "collected_at": "2026-06-11T19:28:52+00:00",
    }])
    detail = build_asm_diskgroup_detail(raw)
    row = detail.iloc[0]
    # Usable columns -- the primary view.
    assert row["usable_total_tb"] == pytest.approx(173.18, abs=0.01)
    assert row["usable_used_tb"] == pytest.approx(81.95, abs=0.01)
    assert row["usable_free_tb"] == pytest.approx(80.0)
    # Raw columns -- preserved.
    assert row["total_tb"] == pytest.approx(519.54)
    assert row["free_tb"] == pytest.approx(273.70)
    assert row["used_tb"] == pytest.approx(245.84, abs=0.01)
    # Mirror factor recorded for transparency.
    assert row["mirror_factor"] == pytest.approx(3.0)


def test_normalize_asm_handles_empty() -> None:
    table = normalize_asm(pd.DataFrame())
    assert table.empty
    assert "usable_total_tb" in table.columns


# ---------------------------------------------------------------------------
# Filesystem size parsing + rollup
# ---------------------------------------------------------------------------


def test_parse_df_size_gb_units() -> None:
    assert parse_df_size_gb("98G") == 98.0
    assert parse_df_size_gb("1.2T") == pytest.approx(1228.8)
    assert parse_df_size_gb("500M") == pytest.approx(500 / 1024, abs=0.001)
    assert parse_df_size_gb("100K") == pytest.approx(100 / (1024 * 1024), abs=0.001)
    assert parse_df_size_gb("50") == pytest.approx(50.0)  # bare numerics -> GB
    assert parse_df_size_gb("") is None
    assert parse_df_size_gb(None) is None
    assert parse_df_size_gb("garbage") is None
    assert parse_df_size_gb("-") is None  # df omits sizes for some pseudo fs


def test_explode_filesystems_parses_sizes_to_gb() -> None:
    inventory = pd.DataFrame([{
        "cluster": "c1", "host": "h1",
        "filesystems": json.dumps([
            {"filesystem": "/dev/sda1", "type": "xfs", "size": "100G",
             "used": "80G", "available": "20G", "use_percent": "80%",
             "mounted_on": "/"},
            {"filesystem": "/dev/sda2", "type": "xfs", "size": "1T",
             "used": "950G", "available": "50G", "use_percent": "95%",
             "mounted_on": "/u01"},
        ]),
    }])
    table = explode_filesystems(inventory)
    assert len(table) == 2
    by_mount = {row["mount"]: row for _, row in table.iterrows()}
    assert by_mount["/"]["size_gb"] == pytest.approx(100.0)
    assert by_mount["/"]["used_gb"] == pytest.approx(80.0)
    assert by_mount["/u01"]["size_gb"] == pytest.approx(1024.0)
    assert by_mount["/u01"]["used_gb"] == pytest.approx(950.0)
    # warning level derived from used %: 95 -> CRITICAL, 80 -> WARNING.
    assert by_mount["/u01"]["warning_level"] == "CRITICAL"
    assert by_mount["/"]["warning_level"] == "WARNING"


def test_build_filesystem_host_rollup_aggregates_per_host() -> None:
    inventory = pd.DataFrame([
        {
            "cluster": "c1", "host": "h1",
            "filesystems": json.dumps([
                {"filesystem": "/dev/sda1", "type": "xfs", "size": "100G",
                 "used": "80G", "available": "20G", "use_percent": "80%",
                 "mounted_on": "/"},
                {"filesystem": "/dev/sda2", "type": "xfs", "size": "200G",
                 "used": "50G", "available": "150G", "use_percent": "25%",
                 "mounted_on": "/u01"},
            ]),
        },
        {
            "cluster": "c1", "host": "h2",
            "filesystems": json.dumps([
                {"filesystem": "/dev/sda1", "type": "xfs", "size": "100G",
                 "used": "95G", "available": "5G", "use_percent": "95%",
                 "mounted_on": "/"},
            ]),
        },
    ])
    rollup = build_filesystem_host_rollup(explode_filesystems(inventory))
    by_host = rollup.set_index(["cluster", "host"])

    h1 = by_host.loc[("c1", "h1")]
    assert h1["filesystems"] == 2
    assert h1["size_gb"] == pytest.approx(300.0)
    assert h1["used_gb"] == pytest.approx(130.0)
    assert h1["max_used_pct"] == pytest.approx(80.0)
    assert h1["critical_count"] == 0
    assert h1["warning_count"] == 1

    h2 = by_host.loc[("c1", "h2")]
    assert h2["critical_count"] == 1
    # h2 should sort above h1 because it has a CRITICAL.
    assert rollup.iloc[0]["host"] == "h2"


def test_build_filesystem_host_rollup_handles_empty() -> None:
    rollup = build_filesystem_host_rollup(pd.DataFrame())
    assert rollup.empty
    assert "max_used_pct" in rollup.columns
