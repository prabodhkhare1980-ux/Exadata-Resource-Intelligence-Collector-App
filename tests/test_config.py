from pathlib import Path

import pytest

from exadata_ric.config import ConfigError, load_config
from inventory import load_inventory


def test_load_sample_config_resolves_users():
    config = load_config(Path("config/clusters.example.yaml"))

    by_name = {host.name: host for host in config.hosts}
    assert by_name["dc04dx26db01"].ssh_user == "srcordma"
    assert by_name["dc04dx26db02"].ssh_user == "srcordma"
    assert by_name["iad3dx02v1-6rdqa1"].ssh_user == "srcordma"
    assert by_name["dc04dx26db01"].auth.method == "key"
    assert config.debug_enabled is False


def test_duplicate_address_same_cluster_fails(tmp_path: Path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text(
        """environments:
  onprem:
    ssh_user: a
clusters:
  - name: c1
    environment: onprem
    hosts:
      - name: h1
        address: x
      - name: h2
        address: x
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_db_memory_warning_thresholds_load_from_sample_config():
    inventory = load_inventory(Path("config/clusters.example.yaml"))

    assert inventory.db_memory_sga_near_max_severity == "info"
    assert inventory.db_memory_sga_near_max_pct == 98
    assert inventory.db_memory_pga_used_pct_target == 80
    assert inventory.db_memory_pga_alloc_pct_target == 100
