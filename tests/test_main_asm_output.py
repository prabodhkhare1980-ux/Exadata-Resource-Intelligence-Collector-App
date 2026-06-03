import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from collectors.asm_diskgroups_collector import ASMDiskgroupRecord
from collectors.db_inventory_collector import DBInventoryRecord
from collectors.os_collector import OSCollectionRecord
from inventory import ClusterConfig, HostConfig, Inventory


def _host() -> HostConfig:
    return HostConfig(
        name="h1",
        address="10.0.0.1",
        user="srcordma",
        environment="prod",
        auth_method="ssh_key",
        private_key=".secrets/ssh/srcordma_id_rsa",
        strict_host_key_checking="accept-new",
        port=22,
        privilege_enabled=True,
        privilege_method="sudo",
        sudo_password_mode="none",
        force_tty=False,
        timeout_seconds=30,
    )


def test_run_writes_asm_outputs(monkeypatch, tmp_path: Path) -> None:
    inv = Inventory(
        clusters=[ClusterConfig(name="c1", environment="prod", hosts=[_host()])],
        output_dir=tmp_path,
        logs_dir=tmp_path / "logs",
        parallel_enabled=False,
    )

    def fake_collect_host(cluster, host, runner, logs_dir, inventory):
        os = OSCollectionRecord(cluster=cluster.name, host=host.name, address=host.address, collected_at="now", status="ok")
        db = DBInventoryRecord(cluster=cluster.name, host=host.name, address=host.address, collected_at="now", status="ok")
        asm = [ASMDiskgroupRecord(cluster=cluster.name, host=host.name, address=host.address, diskgroup_name="DATA", state="MOUNTED", type="EXTERN", total_mb=1000, free_mb=200, usable_file_mb=180, used_pct=80.0, warning_level="OK", asm_collection_status="success")]
        return os, db, asm

    monkeypatch.setattr(main, "_collect_host", fake_collect_host)

    rc = main.run(inv)

    assert rc == 0
    assert (tmp_path / "asm_diskgroups.csv").exists()
    assert (tmp_path / "asm_diskgroups.json").exists()
    assert (tmp_path / "asm_metadata.csv").exists()
    assert (tmp_path / "asm_metadata.json").exists()
    assert (tmp_path / "asm_summary.csv").exists()
    assert (tmp_path / "health_summary.csv").exists()
    assert (tmp_path / "health_summary.json").exists()


def test_asm_script_template_is_deprecated_for_direct_commands() -> None:
    from collectors.asm_diskgroups_collector import ASM_COLLECTION_SCRIPT

    assert "direct SSH commands" in ASM_COLLECTION_SCRIPT
    assert "__ASM_TIMEOUT_SECONDS__" not in ASM_COLLECTION_SCRIPT
