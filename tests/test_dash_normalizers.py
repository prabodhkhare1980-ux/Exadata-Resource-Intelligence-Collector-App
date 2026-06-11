"""Tests for the Dash normalizers service."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.normalizers import (  # noqa: E402
    build_db_performance_summary,
    build_hugepages_node_detail,
    explode_filesystems,
    hugepages_severity,
    normalize_asm,
    normalize_db_memory_history,
    normalize_db_memory_summary,
    normalize_db_performance,
    normalize_hugepages,
    normalize_severity,
    selected_thp_mode,
    severity_from_pct,
    thp_severity,
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
    # Schema gained usable_* columns (redundancy-aware capacity) and the
    # `type` column needed to compute them; assert presence rather than
    # exact ordering so future schema additions are not breaking changes.
    expected_columns = {
        "cluster", "host", "diskgroup_name", "type",
        "total_tb", "free_tb", "usable_tb",
        "usable_total_tb", "usable_used_tb",
        "used_pct", "warning_level",
    }
    assert expected_columns.issubset(set(df.columns))
    assert df["warning_level"].iloc[0] == "WARNING"
    assert df["used_pct"].iloc[0] == 80.0


def test_normalize_hugepages_renames_pascalcase_columns() -> None:
    raw = pd.DataFrame(
        [
            {
                "Cluster": "iad1px01v1-gngym1",
                "Host": "iad1px01v1-gngym1",
                "MemTotal": 1367,
                "HP_Size_KB": 2048,
                "HP_Total": 355840,
                "HP_Free": 269126,
                "HP_Rsvd": 1,
                "HP_Surp": 0,
                "HP_Used": 86714,
                "HP_Used_GB": 169,
                "HP_Total_GB": 695,
                "HP_Pct_of_MemTotal": 50.8,
                "THP_Status": "always [madvise] never",
                "Timestamp": "2026-03-04 16:50:48",
            }
        ]
    )
    df = normalize_hugepages(raw)
    row = df.iloc[0]
    assert row["cluster"] == "iad1px01v1-gngym1"
    assert row["host"] == "iad1px01v1-gngym1"
    assert row["mem_gb"] == 1367
    assert row["hp_total_gb"] == 695
    assert row["hp_used_gb"] == 169
    assert row["hp_free_gb"] == 526  # 269126 * 2048 / 1024 / 1024 = 525.6 -> 526
    # hp_used_pct = 86714 / 355840 * 100 = 24.37 -> 24.37
    assert abs(row["hp_used_pct"] - 24.37) < 0.01
    assert row["hp_alloc_pct_ram"] == 50.8
    assert row["thp_status"] == "always [madvise] never"
    assert row["thp_mode"] == "madvise"
    assert row["severity"] == "WARNING"  # THP madvise overrides
    assert row["timestamp"] == "2026-03-04 16:50:48"


def test_normalize_hugepages_calculates_missing_used_and_free_gb() -> None:
    raw = pd.DataFrame(
        [
            {
                "Cluster": "c1",
                "Host": "h1",
                "HP_Size_KB": 2048,
                "HP_Total": 1000,
                "HP_Free": 250,
                "MemTotal": 100,
                "THP_Status": "always madvise [never]",
            }
        ]
    )
    df = normalize_hugepages(raw)
    row = df.iloc[0]
    assert row["hp_used"] == 750
    # 750 * 2048 / 1024 / 1024 = 1.46 -> 1
    assert row["hp_used_gb"] == 1
    # 250 * 2048 / 1024 / 1024 = 0.488 -> 0
    assert row["hp_free_gb"] == 0
    assert row["hp_used_pct"] == 75.0
    assert row["thp_mode"] == "never"
    # hp_total_gb=2 / mem_gb=100 = 2% allocation, < 40% -> INFO
    assert row["severity"] == "INFO"


def test_selected_thp_mode_variants() -> None:
    assert selected_thp_mode("always [madvise] never") == "madvise"
    assert selected_thp_mode("[always] madvise never") == "always"
    assert selected_thp_mode("always madvise [never]") == "never"
    assert selected_thp_mode("never") == "never"
    assert selected_thp_mode("UNKNOWN") == "unknown"
    assert selected_thp_mode("") == "unknown"
    assert selected_thp_mode(None) == "unknown"


def test_thp_severity_levels() -> None:
    assert thp_severity("always madvise [never]") == "OK"
    assert thp_severity("always [madvise] never") == "WARNING"
    assert thp_severity("[always] madvise never") == "CRITICAL"
    assert thp_severity("UNKNOWN") == "INFO"


def test_hugepages_severity_thresholds() -> None:
    assert hugepages_severity(95, 50, "always madvise [never]") == "CRITICAL"
    assert hugepages_severity(80, 50, "always madvise [never]") == "WARNING"
    assert hugepages_severity(30, 30, "always madvise [never]") == "INFO"
    assert hugepages_severity(30, 50, "always madvise [never]") == "OK"
    # THP critical overrides OK
    assert hugepages_severity(30, 50, "[always] madvise never") == "CRITICAL"


def test_build_hugepages_node_detail_includes_calculated_fields() -> None:
    raw = pd.DataFrame(
        [
            {
                "Cluster": "iad1px01v1-gngym1",
                "Host": "iad1px01v1-gngym1",
                "MemTotal": 1367,
                "HP_Size_KB": 2048,
                "HP_Total": 355840,
                "HP_Free": 269126,
                "HP_Rsvd": 1,
                "HP_Surp": 0,
                "HP_Used": 86714,
                "HP_Used_GB": 169,
                "HP_Total_GB": 695,
                "HP_Pct_of_MemTotal": 50.8,
                "THP_Status": "always [madvise] never",
                "Timestamp": "2026-03-04 16:50:48",
            }
        ]
    )
    df = build_hugepages_node_detail(raw)
    row = df.iloc[0]
    assert row["mem_gb"] == 1367
    assert row["hp_total_gb"] == 695
    assert row["hp_used_gb"] == 169
    assert row["hp_free_gb"] == 526
    assert abs(row["hp_used_pct"] - 24.37) < 0.01
    assert row["hp_alloc_pct_ram"] == 50.8
    assert row["thp_status"] == "always [madvise] never"
    assert row["thp_mode"] == "madvise"
    assert row["severity"] == "WARNING"


def test_build_hugepages_node_detail_empty_input() -> None:
    df = build_hugepages_node_detail(pd.DataFrame())
    assert df.empty
    for column in [
        "cluster",
        "host",
        "mem_gb",
        "hp_total_gb",
        "hp_used_gb",
        "hp_free_gb",
        "hp_used_pct",
        "hp_alloc_pct_ram",
        "thp_status",
        "thp_mode",
        "timestamp",
        "severity",
    ]:
        assert column in df.columns


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
