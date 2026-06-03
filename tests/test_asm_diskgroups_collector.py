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
    rows = [row for row in result.rows if row.get("record_type") != "host_metadata"]
    metadata = [row for row in result.rows if row.get("record_type") == "host_metadata"]
    assert len(rows) == 1
    assert len(metadata) == 1
    row = rows[0]
    assert row["diskgroup_name"] == "DATA"
    assert row["total_mb"] == 1000000
    assert row["free_mb"] == 120000
    assert row["used_pct"] == 88.0
    assert row["warning_level"] == "WARNING"
    assert row["asm_collection_status"] == "success"


def test_parse_includes_asm_debug_fields_on_diskgroup_rows() -> None:
    collector = AsmDiskgroupCollector()
    sections = {
        "asm_status": [["asm_collection_status", "success"]],
        "asm_env": [
            ["grid_home", "/u01/app/19.0.0/grid"],
            ["grid_owner", "oracle"],
            ["asm_sid", "+ASM1"],
            ["asmcmd_path", "/u01/app/19.0.0/grid/bin/asmcmd"],
        ],
        "asm_lsdg": [
            ["State Type Rebal Sector Logical_Sector Block AU Total_MB Free_MB Req_mir_free_MB Usable_file_MB Offline_disks Voting_files Name"],
            ["MOUNTED HIGH N 512 512 4096 4194304 544776192 362123424 0 120702048 2 Y DATAC1/"],
        ],
    }
    result = collector.parse(_host(), sections)
    row = [row for row in result.rows if row.get("record_type") != "host_metadata"][0]
    assert row["asm_collection_status"] == "success"
    assert row["grid_home"] == "/u01/app/19.0.0/grid"
    assert row["grid_owner"] == "oracle"
    assert row["asm_sid"] == "+ASM1"
    assert row["asmcmd_path"] == "/u01/app/19.0.0/grid/bin/asmcmd"


def test_parse_exact_captured_asm_stdout() -> None:
    collector = AsmDiskgroupCollector()
    sections = {
        "asm_status": [["asm_collection_status", "success"]],
        "asm_lsdg": [
            ["State Type Rebal Sector Logical_Sector Block AU Total_MB Free_MB Req_mir_free_MB Usable_file_MB Offline_disks Voting_files Name"],
            ["MOUNTED HIGH N 512 512 4096 4194304 544776192 362123424 0 120702048 2 Y DATAC1/"],
            ["MOUNTED HIGH N 512 512 4096 4194304 944776192 544776192 0 181592064 2 N RECOC1/"],
        ],
    }
    result = collector.parse(_host(), sections)
    rows = [row for row in result.rows if row.get("record_type") != "host_metadata"]
    assert [row["diskgroup_name"] for row in rows] == ["DATAC1", "RECOC1"]
    assert rows[0]["total_mb"] == 544776192
    assert rows[0]["free_mb"] == 362123424
    assert rows[0]["usable_file_mb"] == 120702048
    assert rows[0]["free_pct"] == 66.47
    assert rows[0]["usable_pct"] == 22.16
    assert rows[0]["used_pct"] == 33.53
    assert rows[1]["total_mb"] == 944776192
    assert rows[1]["free_mb"] == 544776192
    assert rows[1]["used_pct"] == 42.34


def test_shell_uses_direct_asmcmd_without_sqlplus_fallback() -> None:
    shell = AsmDiskgroupCollector().shell()
    assert "awk -F: '/^\\+ASM/ {print $1 \"|\" $2; exit}' /etc/oratab" in shell
    assert "ps -eo user,args" in shell
    assert "/[p]mon_\\+ASM/" in shell
    assert "stat -c '%U'" not in shell
    assert "sudo -n -u \"$grid_owner\" env ORACLE_HOME=\"$asm_grid_home\" ORACLE_SID=\"$asm_sid\" PATH=\"$asm_grid_home/bin:/usr/bin:/bin\"" in shell
    assert "sqlplus" not in shell
    assert "<<" not in shell
    assert "mktemp" not in shell
    assert "trap" not in shell
