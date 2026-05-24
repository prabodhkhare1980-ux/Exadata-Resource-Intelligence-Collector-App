from exadata_ric.collectors.asm_diskgroups import AsmDiskgroupCollector
from exadata_ric.config import AuthConfig, HostConfig, PrivilegeConfig


def _host() -> HostConfig:
    return HostConfig(
        cluster="c1",
        environment="prod",
        name="h1",
        address="10.0.0.1",
        ssh_user="srcordma",
        auth=AuthConfig(method="ssh_key", key_file=".secrets/ssh/srcordma_id_rsa"),
        privilege=PrivilegeConfig(enabled=True),
    )


def test_parse_asm_lsdg_rows_with_warning_level() -> None:
    collector = AsmDiskgroupCollector()
    sections = {
        "asm_status": [["asm_collection_status", "success"]],
        "asm_lsdg": [
            ["State    Type  Rebal  Sector  Block       AU  Total_MB   Free_MB  Req_mir_free_MB  Usable_file_MB  Offline_disks  Voting_files  Name"],
            ["MOUNTED  EXTERN N         512   4096  4194304   1000000    120000                0          120000              0             N  DATA/"],
        ]
    }
    result = collector.parse(_host(), sections)
    assert len(result.rows) == 2
    row = result.rows[0]
    assert row["diskgroup_name"] == "DATA"
    assert row["total_mb"] == 1000000
    assert row["free_mb"] == 120000
    assert row["used_pct"] == 88.0
    assert row["warning_level"] == "WARNING"
    assert result.rows[1]["asm_collection_status"] == "success"
