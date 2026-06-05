from pathlib import Path

from inventory import load_inventory


def test_db_memory_warning_thresholds_load_from_sample_config():
    inventory = load_inventory(Path("config/clusters.example.yaml"))

    assert inventory.db_memory_sga_near_max_severity == "info"
    assert inventory.db_memory_sga_near_max_pct == 98
    assert inventory.db_memory_pga_used_pct_target == 80
    assert inventory.db_memory_pga_alloc_pct_target == 100
