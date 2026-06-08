"""Unit tests for Streamlit DB memory analytics helpers."""

import importlib.util
from pathlib import Path

import pandas as pd

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("dashboard_app", APP_PATH)
assert SPEC and SPEC.loader
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


def test_normalize_db_memory_summary_parses_numeric_dates_and_severity() -> None:
    source = pd.DataFrame(
        [
            {
                "Cluster": "cluster-a",
                "db_unique_name": "DBA",
                "DB_NAME": "DBA",
                "INSTANCE_NAME": "DBA1",
                "HOST_NAME": "db01",
                "snapshot_count": "12",
                "begin_time_min": "2026-05-01 00:00:00",
                "end_time_max": "2026-05-02 00:00:00",
                "sga_used_gb_max": ".03",
                "pga_allocated_gb_max": "4.5",
                "warning_severity": "info",
            }
        ]
    )

    result = app.normalize_db_memory_summary(source)

    assert result.loc[0, "cluster"] == "cluster-a"
    assert result.loc[0, "host_name"] == "db01"
    assert result.loc[0, "snapshot_count"] == 12
    assert result.loc[0, "sga_used_gb_max"] == 0.03
    assert result.loc[0, "pga_allocated_gb_max"] == 4.5
    assert pd.api.types.is_datetime64_any_dtype(result["begin_time_min"])
    assert pd.api.types.is_datetime64_any_dtype(result["end_time_max"])
    assert result.loc[0, "warning_severity"] == "INFO"
    assert result.loc[0, "warning_level"] == "INFO"


def test_info_severity_is_supported() -> None:
    assert app.HEALTH_LEVELS == ["CRITICAL", "WARNING", "INFO", "OK"]
    assert app.normalize_severity(" info ") == "INFO"
    assert app.normalize_warning_level(" info ") == "INFO"
    assert app.LEVEL_COLORS["INFO"]
    assert app.LEVEL_BACKGROUNDS["INFO"]


def test_warning_cell_style_supports_info_severity() -> None:
    first_column_style = app.warning_cell_style("cluster", "cluster", "INFO")
    other_column_style = app.warning_cell_style("host", "cluster", "INFO")

    assert first_column_style == (
        "background-color: #eff6ff; border-left: 4px solid #2563eb"
    )
    assert other_column_style == "background-color: #eff6ff"


def test_apply_warning_style_supports_info_severity() -> None:
    source = pd.DataFrame(
        [{"cluster": "cluster-a", "warning_level": "INFO"}]
    )

    result = app.apply_warning_style(source)

    assert result.loc[0, "cluster"] == (
        "background-color: #eff6ff; border-left: 4px solid #2563eb"
    )
    assert result.loc[0, "warning_level"] == "background-color: #eff6ff"


def test_build_memory_cluster_rollup_provides_missing_file_fallback() -> None:
    summary = app.normalize_db_memory_summary(
        pd.DataFrame(
            [
                {
                    "Cluster": "cluster-a",
                    "INSTANCE_NAME": "DB1A",
                    "sga_used_gb_max": "10",
                    "pga_allocated_gb_max": "3",
                    "sga_max_size_gb_max": "16",
                    "pga_aggregate_target_gb_max": "4",
                    "warning_severity": "CRITICAL",
                },
                {
                    "Cluster": "cluster-a",
                    "INSTANCE_NAME": "DB1B",
                    "sga_used_gb_max": "8",
                    "pga_allocated_gb_max": "2",
                    "sga_max_size_gb_max": "12",
                    "pga_aggregate_target_gb_max": "3",
                    "warning_severity": "INFO",
                },
            ]
        )
    )

    rollup = app.build_memory_cluster_rollup(summary)

    assert len(rollup) == 1
    assert rollup.loc[0, "db_instances"] == 2
    assert rollup.loc[0, "total_sga_used_gb_max"] == 18
    assert rollup.loc[0, "total_pga_allocated_gb_max"] == 5
    assert rollup.loc[0, "critical_count"] == 1
    assert rollup.loc[0, "warning_count"] == 0
    assert rollup.loc[0, "info_count"] == 1


def test_normalize_db_memory_history_includes_sga_components_and_warning_counts() -> None:
    result = app.normalize_db_memory_history(
        pd.DataFrame(
            [
                {
                    "SGA_BUFFER_CACHE_GB": ".03",
                    "SGA_SHARED_POOL_GB": "1.2",
                    "SGA_OTHER_GB": "0.4",
                    "warning_severity": "warning",
                    "info_warnings": "SGA_NEAR_MAX",
                    "warning_warnings": "PGA_TARGET_HIGH",
                    "critical_warnings": "",
                }
            ]
        )
    )

    assert result.loc[0, "sga_buffer_cache_gb"] == 0.03
    assert result.loc[0, "sga_shared_pool_gb"] == 1.2
    assert result.loc[0, "sga_other_gb"] == 0.4
    assert result.loc[0, "warning_severity"] == "WARNING"
    assert result.loc[0, "info_warnings"] == "SGA_NEAR_MAX"
    assert result.loc[0, "warning_warnings"] == "PGA_TARGET_HIGH"


def test_unused_memory_analytics_output_constants_are_removed() -> None:
    assert not hasattr(app, "MEMORY_ANALYTICS_REQUIRED_OUTPUTS")
    assert not hasattr(app, "MEMORY_ANALYTICS_OPTIONAL_OUTPUTS")


def test_version_inventory_uses_health_feed_for_missing_imageinfo() -> None:
    version_inventory = pd.DataFrame(
        [
            {"cluster": "c1", "host": "h1", "warning_level": "OK"},
            {"cluster": "c1", "host": "h2", "warning_level": "OK"},
        ]
    )
    health_summary = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host": "h1",
                "category": "VERSION_INVENTORY",
                "metric": "imageinfo_available",
                "warning_level": "WARNING",
            }
        ]
    )

    result = app.apply_version_inventory_health(version_inventory, health_summary)

    h1 = result[result["host"] == "h1"].iloc[0]
    h2 = result[result["host"] == "h2"].iloc[0]
    assert bool(h1["missing_imageinfo"]) is True
    assert h1["warning_level"] == "WARNING"
    assert bool(h2["missing_imageinfo"]) is False
    assert h2["warning_level"] == "OK"


def test_optional_memory_normalizers_handle_empty_and_partial_frames() -> None:
    normalizers = [
        app.normalize_memory_capacity_top_consumers,
        app.normalize_memory_warning_report,
        app.normalize_memory_rightsizing_candidates,
        app.normalize_memory_cluster_rollup,
    ]

    for normalizer in normalizers:
        assert normalizer(pd.DataFrame()).empty
        partial = normalizer(pd.DataFrame([{"Cluster": "cluster-a"}]))
        assert partial.loc[0, "cluster"] == "cluster-a"


def test_optional_memory_normalizers_convert_numeric_and_severity_fields() -> None:
    consumers = app.normalize_memory_capacity_top_consumers(
        pd.DataFrame(
            [
                {
                    "Cluster": "cluster-a",
                    "DB_NAME": "DBA",
                    "INSTANCE_NAME": "DBA1",
                    "HOST_NAME": "db01",
                    "sga_used_gb_max": ".03",
                    "pga_allocated_gb_max": "4.5",
                    "warning_severity": "info",
                }
            ]
        )
    )
    rightsizing = app.normalize_memory_rightsizing_candidates(
        pd.DataFrame([{"current_value": "16", "observed_peak": "8.25"}])
    )

    assert consumers.loc[0, "sga_used_gb_max"] == 0.03
    assert consumers.loc[0, "pga_allocated_gb_max"] == 4.5
    assert consumers.loc[0, "warning_severity"] == "INFO"
    assert consumers.loc[0, "host_name"] == "db01"
    assert rightsizing.loc[0, "current_value"] == 16
    assert rightsizing.loc[0, "observed_peak"] == 8.25


def test_memory_analytics_navigation_follows_db_memory_history() -> None:
    assert "Memory Analytics" in app.NAVIGATION
    assert app.NAVIGATION.index("Memory Analytics") == app.NAVIGATION.index(
        "DB Memory History"
    ) + 1
