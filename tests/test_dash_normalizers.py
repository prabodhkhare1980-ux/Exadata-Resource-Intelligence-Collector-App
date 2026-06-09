"""Tests for the Dash normalizers service."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.normalizers import (  # noqa: E402
    build_db_performance_summary,
    explode_filesystems,
    normalize_asm,
    normalize_db_memory_history,
    normalize_db_memory_summary,
    normalize_db_performance,
    normalize_hugepages,
    normalize_severity,
    severity_from_pct,
)


def test_severity_from_pct_thresholds() -> None:
    assert severity_from_pct(95) == "CRITICAL"
    assert severity_from_pct(85) == "WARNING"
    assert severity_from_pct(50) == "OK"
    assert severity_from_pct(None) == "OK"
    assert severity_from_pct(float("nan")) == "OK"
    assert severity_from_pct("bad") == "OK"


def test_severity_from_pct_custom_thresholds() -> None:
    assert severity_from_pct(70, warning=60, critical=80) == "WARNING"
    assert severity_from_pct(85, warning=60, critical=80) == "CRITICAL"


def test_normalize_severity_unknown_value() -> None:
    assert normalize_severity("critical") == "CRITICAL"
    assert normalize_severity("nope") == "OK"
    assert normalize_severity(None) == "OK"
    assert normalize_severity(float("nan")) == "OK"


def test_normalize_asm_fills_used_pct_when_missing() -> None:
    raw = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host": "h1",
                "diskgroup_name": "DATA",
                "total_tb": 10.0,
                "free_tb": 2.0,
                "warning_level": "warning",
            }
        ]
    )
    df = normalize_asm(raw)
    assert list(df.columns) == [
        "cluster",
        "host",
        "diskgroup_name",
        "total_tb",
        "free_tb",
        "usable_tb",
        "used_pct",
        "warning_level",
    ]
    assert df["warning_level"].iloc[0] == "WARNING"
    assert df["used_pct"].iloc[0] == 80.0


def test_normalize_hugepages_derives_pct() -> None:
    raw = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host": "h1",
                "hugepages_total": 1000,
                "hugepages_free": 250,
                "warning_level": "ok",
            }
        ]
    )
    df = normalize_hugepages(raw)
    assert df["hugepages_used_pct"].iloc[0] == 75.0
    assert df["hugepages_free_pct"].iloc[0] == 25.0
    assert df["warning_level"].iloc[0] == "OK"


def test_normalize_db_performance_renames_uppercase() -> None:
    raw = pd.DataFrame(
        [
            {
                "Cluster": "c1",
                "HOST_NAME": "h1",
                "DB_NAME": "ORCL",
                "INSTANCE_NAME": "ORCL1",
                "BEGIN_TIME": "2026-01-01T00:00:00",
                "END_TIME": "2026-01-01T01:00:00",
                "TOTAL_IOPS_AVG": 1000,
                "TOTAL_IOPS_MAX": 1500,
                "TOTAL_MBPS_AVG": 200,
                "TOTAL_MBPS_MAX": 300,
                "CPU_USAGE_PER_SEC_AVG": 1.0,
                "CPU_USAGE_PER_SEC_MAX": 2.5,
                "HOST_CPU_UTIL_PCT_AVG": 40.0,
                "HOST_CPU_UTIL_PCT_MAX": 70.0,
            }
        ]
    )
    df = normalize_db_performance(raw)
    expected = {
        "cluster",
        "host_name",
        "db_name",
        "instance_name",
        "begin_time",
        "end_time",
        "total_iops_avg",
        "total_iops_max",
        "total_mbps_avg",
        "total_mbps_max",
        "cpu_usage_per_sec_avg",
        "cpu_usage_per_sec_max",
        "host_cpu_util_pct_avg",
        "host_cpu_util_pct_max",
    }
    assert expected.issubset(df.columns)
    assert pd.notna(df["end_time"].iloc[0])
    assert df["total_iops_max"].iloc[0] == 1500


def test_build_db_performance_summary_aggregates() -> None:
    raw = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host_name": "h1",
                "db_name": "ORCL",
                "instance_name": "ORCL1",
                "begin_time": "2026-01-01T00:00:00",
                "end_time": "2026-01-01T01:00:00",
                "total_iops_avg": 100,
                "total_iops_max": 150,
                "total_mbps_avg": 10,
                "total_mbps_max": 20,
                "cpu_usage_per_sec_avg": 1.0,
                "cpu_usage_per_sec_max": 2.0,
                "host_cpu_util_pct_avg": 40,
                "host_cpu_util_pct_max": 60,
            },
            {
                "cluster": "c1",
                "host_name": "h1",
                "db_name": "ORCL",
                "instance_name": "ORCL1",
                "begin_time": "2026-01-01T01:00:00",
                "end_time": "2026-01-01T02:00:00",
                "total_iops_avg": 200,
                "total_iops_max": 400,
                "total_mbps_avg": 30,
                "total_mbps_max": 60,
                "cpu_usage_per_sec_avg": 3.0,
                "cpu_usage_per_sec_max": 5.0,
                "host_cpu_util_pct_avg": 50,
                "host_cpu_util_pct_max": 90,
            },
        ]
    )
    summary = build_db_performance_summary(raw)
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["snapshot_count"] == 2
    assert row["max_total_iops"] == 400
    assert row["max_total_mbps"] == 60
    assert row["max_host_cpu_util_pct"] == 90
    assert abs(row["avg_total_iops"] - 150) < 1e-6


def test_build_db_performance_summary_empty_input_returns_columns() -> None:
    summary = build_db_performance_summary(pd.DataFrame())
    assert summary.empty
    assert "max_total_iops" in summary.columns


def test_explode_filesystems_parses_nested_list() -> None:
    raw = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host": "h1",
                "filesystems": [
                    {"filesystem": "/dev/sda1", "mounted_on": "/", "use_pct": "97%"},
                    {"filesystem": "/dev/sda2", "mounted_on": "/var", "use_pct": "20%"},
                ],
            }
        ]
    )
    df = explode_filesystems(raw)
    assert len(df) == 2
    assert df["used_pct"].max() == 97
    severities = df["warning_level"].tolist()
    assert "CRITICAL" in severities


def test_explode_filesystems_parses_json_string() -> None:
    raw = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host": "h1",
                "filesystems": '[{"filesystem": "/dev/sda1", "mounted_on": "/", "use_pct": "10%"}]',
            }
        ]
    )
    df = explode_filesystems(raw)
    assert len(df) == 1
    assert df["mount"].iloc[0] == "/"


def test_explode_filesystems_empty_input_returns_empty() -> None:
    df = explode_filesystems(pd.DataFrame())
    assert df.empty


def test_normalize_db_memory_history_basic() -> None:
    raw = pd.DataFrame(
        [
            {
                "Cluster": "c1",
                "HOST_NAME": "h1",
                "DB_NAME": "ORCL",
                "INSTANCE_NAME": "ORCL1",
                "END_TIME": "2026-01-01T00:00:00",
                "SGA_TARGET_GB": 32,
                "warning_severity": "warning",
            }
        ]
    )
    df = normalize_db_memory_history(raw)
    assert "sga_target_gb" in df.columns
    assert df["warning_severity"].iloc[0] == "WARNING"


def test_normalize_db_memory_summary_basic() -> None:
    raw = pd.DataFrame(
        [
            {
                "Cluster": "c1",
                "DB_NAME": "ORCL",
                "INSTANCE_NAME": "ORCL1",
                "HOST_NAME": "h1",
                "sga_used_gb_max": 24.0,
                "warning_severity": "ok",
            }
        ]
    )
    df = normalize_db_memory_summary(raw)
    assert df["warning_severity"].iloc[0] == "OK"
    assert df["sga_used_gb_max"].iloc[0] == 24.0
