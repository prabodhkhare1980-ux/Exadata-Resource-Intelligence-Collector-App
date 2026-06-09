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


def test_navigation_groups_flatten_to_expected_pages() -> None:
    expected_groups = [
        "Overview",
        "DB Resource Analytics",
        "OS Resource Analytics",
        "Storage Analytics",
        "Inventory",
        "Explore",
    ]
    assert list(app.NAVIGATION_GROUPS.keys()) == expected_groups
    assert app.NAVIGATION_GROUPS["DB Resource Analytics"] == [
        "DB Memory Analytics",
        "DB CPU Analytics",
        "DB IOPS Analytics",
        "DB Throughput Analytics",
    ]
    assert app.NAVIGATION_GROUPS["OS Resource Analytics"] == [
        "OS CPU Analytics",
        "OS Memory Analytics",
        "HugePages Analytics",
        "Filesystem Analytics",
    ]
    assert app.NAVIGATION_GROUPS["Storage Analytics"] == ["ASM Analytics"]
    assert app.flatten_navigation_groups(app.NAVIGATION_GROUPS) == app.NAVIGATION


def test_db_performance_summary_alias_matches_legacy_helper() -> None:
    table = pd.DataFrame(
        [
            {
                "Cluster": "c1", "DB_NAME": "DB1", "INSTANCE_NAME": "DB1A",
                "HOST_NAME": "h1", "BEGIN_TIME": "2026-06-01 00:00:00",
                "END_TIME": "2026-06-01 01:00:00",
                "TOTAL_IOPS_AVG": "100", "TOTAL_IOPS_MAX": "200",
                "TOTAL_MBPS_AVG": "5", "TOTAL_MBPS_MAX": "9",
                "CPU_USAGE_PER_SEC_AVG": "1", "CPU_USAGE_PER_SEC_MAX": "2",
                "HOST_CPU_UTIL_PCT_AVG": "10", "HOST_CPU_UTIL_PCT_MAX": "20",
            }
        ]
    )
    legacy = app.build_performance_summary(table)
    alias = app.build_db_performance_summary(table)
    pd.testing.assert_frame_equal(legacy, alias)


@pytest.mark.parametrize(
    "renderer",
    [
        app.render_db_cpu_analytics_page,
        app.render_db_iops_analytics_page,
        app.render_db_throughput_analytics_page,
    ],
)
def test_analytics_pages_handle_missing_db_performance(monkeypatch, renderer) -> None:
    intro = Mock()
    no_data = Mock()
    monkeypatch.setattr(app, "read_output", lambda stem: (pd.DataFrame(), None))
    monkeypatch.setattr(app, "render_analytics_intro", intro)
    monkeypatch.setattr(app, "show_no_data_message", no_data)

    renderer({})

    intro.assert_called_once_with(None, 0)
    no_data.assert_called_once_with(
        "db_performance output",
        "python main.py --collector db-performance",
    )


def test_show_no_data_message_includes_output_and_command(monkeypatch) -> None:
    warning = Mock()
    caption = Mock()
    code = Mock()
    monkeypatch.setattr(app.st, "warning", warning)
    monkeypatch.setattr(app.st, "caption", caption)
    monkeypatch.setattr(app.st, "code", code)

    app.show_no_data_message("sample output", "python main.py --collector sample")

    warning.assert_called_once_with("No data is available from sample output.")
    caption.assert_called_once()
    code.assert_called_once_with(
        "python main.py --collector sample", language="bash"
    )


def test_top_ranking_chart_uses_horizontal_compact_labels() -> None:
    source = pd.DataFrame(
        [
            {"db_instance": "DB1 / DB1A / db01", "value": 10, "cluster": "c1"},
            {"db_instance": "DB2 / DB2A / db02", "value": 20, "cluster": "c2"},
        ]
    )

    figure = app.top_ranking_chart(
        source,
        label_column="db_instance",
        value_column="value",
        color_column="cluster",
        title="Top consumers",
    )

    assert all(trace.orientation == "h" for trace in figure.data)
    assert figure.layout.xaxis.tickangle == -30
    assert figure.layout.yaxis.automargin is True
