"""Tests for the reorganized dashboard navigation and supporting helpers."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("dashboard_nav_reorg_app", APP_PATH)
assert SPEC and SPEC.loader
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


def test_flatten_navigation_groups_preserves_order() -> None:
    flat = app.flatten_navigation_groups(app.NAVIGATION_GROUPS)
    assert flat == app.NAVIGATION
    assert flat[0] == "Executive Cockpit"
    assert "ASM Analytics" in flat
    assert "Filesystem Analytics" in flat


def test_page_renderers_cover_every_navigation_page() -> None:
    missing = [page for page in app.NAVIGATION if page not in app.PAGE_RENDERERS]
    assert missing == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [(79.9, "OK"), (80, "WARNING"), (89.9, "WARNING"), (90, "CRITICAL"), (None, "OK")],
)
def test_severity_from_pct_thresholds(value: object, expected: str) -> None:
    assert app.severity_from_pct(value) == expected


def test_explode_filesystems_handles_json_payload() -> None:
    inventory = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host": "h1",
                "filesystems": json.dumps(
                    [
                        {"filesystem": "/dev/sda1", "mount": "/", "used_pct": "85"},
                        {"filesystem": "/dev/sda2", "mount": "/u01", "used_pct": "95"},
                    ]
                ),
            }
        ]
    )
    table = app.explode_filesystems(inventory)
    assert len(table) == 2
    by_mount = {row["mount"]: row for _, row in table.iterrows()}
    assert by_mount["/"]["warning_level"] == "WARNING"
    assert by_mount["/u01"]["warning_level"] == "CRITICAL"


def test_os_memory_parsing_from_meminfo_json_and_text() -> None:
    sample = {
        "MemTotal": "33554432 kB",
        "MemFree": "1048576 kB",
        "MemAvailable": "16777216 kB",
        "SwapTotal": "8388608 kB",
        "SwapFree": "8388608 kB",
    }
    inventory = pd.DataFrame(
        [
            {
                "cluster": "c1",
                "host": "h1",
                "hostname": "h1",
                "status": "ok",
                "meminfo_json": json.dumps(sample),
            },
            {
                "cluster": "c1",
                "host": "h2",
                "hostname": "h2",
                "status": "ok",
                "meminfo": "MemTotal: 16777216 kB\nMemFree: 8388608 kB\nMemAvailable: 8388608 kB",
            },
        ]
    )
    table = app.build_os_memory_table(inventory)
    assert len(table) == 2
    h1 = table[table["host"] == "h1"].iloc[0]
    assert h1["mem_total_gb"] == pytest.approx(32.0)
    assert h1["mem_available_gb"] == pytest.approx(16.0)
    assert h1["swap_total_gb"] == pytest.approx(8.0)
    assert h1["swap_used_gb"] == pytest.approx(0.0)
    h2 = table[table["host"] == "h2"].iloc[0]
    assert h2["mem_total_gb"] == pytest.approx(16.0)
    assert h2["mem_available_gb"] == pytest.approx(8.0)


def test_add_pct_columns_handles_zero_total() -> None:
    df = pd.DataFrame(
        [
            {"used": 80, "total": 100},
            {"used": 50, "total": 0},
        ]
    )
    result = app.add_pct_columns(df, "used", "total", "used_pct")
    assert result.loc[0, "used_pct"] == 80.0
    assert pd.isna(result.loc[1, "used_pct"])


@pytest.mark.parametrize(
    "renderer",
    [
        app.render_os_cpu_analytics_page,
        app.render_os_memory_analytics_page,
        app.render_filesystem_analytics_page,
    ],
)
def test_new_pages_handle_empty_os_inventory(monkeypatch, renderer) -> None:
    intro = Mock()
    no_data = Mock()
    monkeypatch.setattr(app, "read_output", lambda stem: (pd.DataFrame(), None))
    monkeypatch.setattr(app, "render_analytics_intro", intro)
    monkeypatch.setattr(app, "show_no_data_message", no_data)

    renderer({})

    intro.assert_called_once_with(None, 0)
    no_data.assert_called_once_with(
        "os_inventory output",
        "python main.py --collector os",
    )


def test_back_compat_aliases_resolve_to_new_renderers() -> None:
    assert app.render_cpu_analytics_page is app.render_db_cpu_analytics_page
    assert app.render_iops_analytics_page is app.render_db_iops_analytics_page
    assert app.render_memory_analytics_page is app.render_db_memory_analytics_page
