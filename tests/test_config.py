from pathlib import Path

from inventory import load_inventory


def test_db_memory_warning_thresholds_load_from_sample_config():
    inventory = load_inventory(Path("config/clusters.example.yaml"))

    assert inventory.db_memory_sga_near_max_severity == "info"
    assert inventory.db_memory_sga_near_max_pct == 98
    assert inventory.db_memory_pga_used_pct_target == 80
    assert inventory.db_memory_pga_alloc_pct_target == 100


def test_host_timeout_defaults_to_documented_120_seconds(tmp_path: Path) -> None:
    config_path = tmp_path / "minimal.yaml"
    config_path.write_text(
        """
environments:
  prod:
    ssh_user: srcordma
    auth:
      method: ssh_key
      private_key: .secrets/ssh/srcordma_id_rsa
clusters:
  - name: c1
    environment: prod
    hosts:
      - name: h1
        address: h1.example.internal
""".strip(),
        encoding="utf-8",
    )

    inventory = load_inventory(config_path)

    assert inventory.clusters[0].hosts[0].timeout_seconds == 120
