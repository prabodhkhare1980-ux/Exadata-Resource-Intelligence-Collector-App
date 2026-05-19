from pathlib import Path

import pytest

from exadata_ric.config import ConfigError, load_config


def test_load_sample_config_resolves_users():
    config = load_config(Path("config/clusters.example.yaml"))

    by_name = {host.name: host for host in config.hosts}
    assert by_name["dc04dx26db01"].ssh_user == "srcordma"
    assert by_name["dc04dx26db02"].ssh_user == "srcordma"
    assert by_name["iad3dx02v1-6rdqa1"].ssh_user == "srcordma"
    assert by_name["dc04dx26db01"].auth.method == "key"


def test_duplicate_address_same_cluster_fails(tmp_path: Path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("""environments:
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
""", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(cfg)
