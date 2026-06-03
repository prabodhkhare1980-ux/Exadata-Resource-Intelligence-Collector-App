from pathlib import Path

from exadata_ric.cli import main
from exadata_ric.collectors import CollectionResult
from exadata_ric.config import AuthConfig, CollectionConfig, HostConfig, PrivilegeConfig


def _host() -> HostConfig:
    return HostConfig(
        name="db01",
        address="10.0.0.1",
        cluster="rac01",
        environment="prod",
        ssh_user="srcordma",
        auth=AuthConfig(method="key"),
        privilege=PrivilegeConfig(),
    )


def test_main_writes_asm_outputs(monkeypatch, tmp_path: Path) -> None:
    config = CollectionConfig(output_dir=tmp_path, hosts=(_host(),))

    def fake_load_config(_: str) -> CollectionConfig:
        return config

    def fake_collect(*args, **kwargs):
        rows = [
            {
                "cluster": "rac01",
                "host": "db01",
                "address": "10.0.0.1",
                "diskgroup_name": "DATA",
                "state": "MOUNTED",
                "type": "EXTERN",
                "total_mb": 1000,
                "free_mb": 250,
                "usable_file_mb": 200,
                "used_pct": 75.0,
                "warning_level": "OK",
            },
            {"cluster": "rac01", "host": "db01", "address": "10.0.0.1", "asm_collection_status": "success"},
        ]
        return [CollectionResult("asm_diskgroups", rows)], []

    monkeypatch.setattr("exadata_ric.cli.load_config", fake_load_config)
    monkeypatch.setattr("exadata_ric.cli.collect", fake_collect)

    rc = main(["--config", "ignored"])

    assert rc == 0
    assert (tmp_path / "asm_diskgroups.json").exists()
    assert (tmp_path / "asm_diskgroups.csv").exists()
    assert (tmp_path / "asm_metadata.json").exists()
    assert (tmp_path / "asm_metadata.csv").exists()
    assert (tmp_path / "asm_summary.csv").exists()
