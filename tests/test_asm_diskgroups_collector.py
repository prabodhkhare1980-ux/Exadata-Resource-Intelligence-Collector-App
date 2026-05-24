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


def test_parse_includes_asm_debug_fields_on_failure() -> None:
    collector = AsmDiskgroupCollector()
    sections = {
        "asm_status": [["asm_collection_status", "failed"], ["asm_collection_error", "missing asmcmd"]],
        "asm_env": [
            ["grid_home", "/u01/app/19.0.0/grid"],
            ["grid_owner", "oracle"],
            ["asm_sid", "+ASM1"],
            ["asmcmd_path", "/u01/app/19.0.0/grid/bin/asmcmd"],
        ],
        "asm_lsdg": [],
    }
    result = collector.parse(_host(), sections)
    status_row = result.rows[-1]
    assert status_row["asm_collection_status"] == "failed"
    assert status_row["grid_home"] == "/u01/app/19.0.0/grid"
    assert status_row["grid_owner"] == "oracle"
    assert status_row["asm_sid"] == "+ASM1"
    assert status_row["asmcmd_path"] == "/u01/app/19.0.0/grid/bin/asmcmd"
    assert status_row["asm_collection_error"] == "missing asmcmd"


def test_shell_supports_dynamic_grid_owner_and_sqlplus_fallback() -> None:
    shell = AsmDiskgroupCollector().shell()
    assert "awk -F: '/^\\+ASM/ {print $1 \"|\" $2; exit}' /etc/oratab" in shell
    assert "stat -c '%U' \"$asm_grid_home/bin/crsctl\"" in shell
    assert "stat -c '%U' \"$asmcmd_path\"" in shell
    assert "sudo -n -u \"$grid_owner\" env ORACLE_HOME=\"$asm_grid_home\" ORACLE_SID=\"$asm_sid\"" in shell
    assert "sqlplus -s / as sysasm <<'SQL'" in shell


def test_shell_has_missing_asmcmd_validation() -> None:
    shell = AsmDiskgroupCollector().shell()
    assert "[ ! -f \"$asmcmd_path\" ]" in shell
