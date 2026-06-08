"""Unit tests for CPU and IOPS dashboard analytics helpers."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("performance_dashboard_app", APP_PATH)
assert SPEC and SPEC.loader
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


def test_build_performance_summary_aggregates_valid_snapshots() -> None:
    source = pd.DataFrame(
        [
            {
                "Cluster": "cluster-a",
                "DB_NAME": "DB1",
                "INSTANCE_NAME": "DB1A",
                "HOST_NAME": "db01",
                "BEGIN_TIME": "2026-06-01 00:00:00",
                "END_TIME": "2026-06-01 01:00:00",
                "TOTAL_IOPS_AVG": "100",
                "TOTAL_IOPS_MAX": "180",
                "TOTAL_MBPS_AVG": "10",
                "TOTAL_MBPS_MAX": "18",
                "CPU_USAGE_PER_SEC_AVG": "2",
                "CPU_USAGE_PER_SEC_MAX": "4",
                "HOST_CPU_UTIL_PCT_AVG": "40",
                "HOST_CPU_UTIL_PCT_MAX": "70",
            },
            {
                "Cluster": "cluster-a",
                "DB_NAME": "DB1",
                "INSTANCE_NAME": "DB1A",
                "HOST_NAME": "db01",
                "BEGIN_TIME": "2026-06-01 01:00:00",
                "END_TIME": "2026-06-01 02:00:00",
                "TOTAL_IOPS_AVG": "300",
                "TOTAL_IOPS_MAX": "450",
                "TOTAL_MBPS_AVG": "30",
                "TOTAL_MBPS_MAX": "45",
                "CPU_USAGE_PER_SEC_AVG": "6",
                "CPU_USAGE_PER_SEC_MAX": "9",
                "HOST_CPU_UTIL_PCT_AVG": "60",
                "HOST_CPU_UTIL_PCT_MAX": "92",
            },
            {
                "Cluster": "cluster-a",
                "DB_NAME": "DB1",
                "INSTANCE_NAME": "DB1A",
                "HOST_NAME": "db01",
                "BEGIN_TIME": "2026-06-01 02:00:00",
                "END_TIME": "not-a-date",
                "TOTAL_IOPS_AVG": "99999",
                "TOTAL_IOPS_MAX": "99999",
            },
        ]
    )

    result = app.build_performance_summary(source)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["snapshot_count"] == 2
    assert row["begin_time_min"] == pd.Timestamp("2026-06-01 00:00:00")
    assert row["end_time_max"] == pd.Timestamp("2026-06-01 02:00:00")
    assert row["avg_total_iops"] == 200
    assert row["max_total_iops"] == 450
    assert row["avg_total_mbps"] == 20
    assert row["max_total_mbps"] == 45
    assert row["avg_db_cpu_per_sec"] == 4
    assert row["max_db_cpu_per_sec"] == 9
    assert row["avg_host_cpu_util_pct"] == 50
    assert row["max_host_cpu_util_pct"] == 92


@pytest.mark.parametrize(
    ("host_cpu", "expected"),
    [(79.9, "INFO"), (80, "WARNING"), (89.9, "WARNING"), (90, "CRITICAL"), (None, "INFO")],
)
def test_cpu_performance_severity_thresholds(host_cpu: object, expected: str) -> None:
    assert app.cpu_performance_severity(host_cpu) == expected


@pytest.mark.parametrize(
    ("iops", "mbps", "expected"),
    [
        (4999, 499, "OK"),
        (5000, 100, "WARNING"),
        (100, 500, "WARNING"),
        (10000, 100, "CRITICAL"),
        (100, 1000, "CRITICAL"),
        ("bad", None, "OK"),
    ],
)
def test_iops_performance_severity_thresholds(
    iops: object, mbps: object, expected: str
) -> None:
    assert app.iops_performance_severity(iops, mbps) == expected


def test_performance_navigation_pages_follow_db_performance() -> None:
    db_performance_index = app.NAVIGATION.index("DB Performance")
    assert app.NAVIGATION[db_performance_index + 1:db_performance_index + 3] == [
        "CPU Analytics",
        "IOPS Analytics",
    ]


@pytest.mark.parametrize(
    "renderer",
    [app.render_cpu_analytics_page, app.render_iops_analytics_page],
)
def test_analytics_pages_handle_missing_db_performance(monkeypatch, renderer) -> None:
    warning = Mock()
    monkeypatch.setattr(app, "read_output", lambda stem: (pd.DataFrame(), None))
    monkeypatch.setattr(app.st, "warning", warning)

    renderer({})

    warning.assert_called_once_with(
        "No db_performance output found. Run the DB performance collector first."
    )
