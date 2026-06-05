import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from types import SimpleNamespace

from collectors.asm_diskgroups_collector import ASMDiskgroupCollector


class _Runner:
    def __init__(self, results):
        self.results = list(results)
        self.commands = []

    def run_command(self, host, command):
        self.commands.append(command)
        return self.results.pop(0)


def _host():
    return SimpleNamespace(name="h1", address="1.1.1.1")


def test_direct_command_collection_success() -> None:
    runner = _Runner([
        SimpleNamespace(ok=True, stdout="+ASM1|/u01/app/23.0.0.0/grid\n", stderr="", error=None, returncode=0),
        SimpleNamespace(ok=True, stdout="grid|asm_pmon_+ASM1\n", stderr="", error=None, returncode=0),
        SimpleNamespace(
            ok=True,
            stdout="\n".join([
                "State Type Rebal Sector Logical_Sector Block AU Total_MB Free_MB Req_mir_free_MB Usable_file_MB Offline_disks Voting_files Name",
                "MOUNTED HIGH N 512 512 4096 4194304 301989888 124454028 0 41474256 0 N DATAC1/",
                "MOUNTED HIGH N 512 512 4096 4194304 75497472 48650676 0 16206624 0 N RECOC1/",
            ]),
            stderr="",
            error=None,
            returncode=0,
        ),
    ])
    collector = ASMDiskgroupCollector(runner)
    rows = collector.collect_host("c1", _host(), __import__('logging').getLogger('t'))

    metadata = [row for row in rows if row.record_type == "host_metadata"]
    diskgroup_rows = [row for row in rows if row.record_type != "host_metadata"]
    assert len(metadata) == 1
    assert "DATAC1/" in metadata[0].asmcmd_stdout
    assert [row.diskgroup_name for row in diskgroup_rows] == ["DATAC1", "RECOC1"]
    assert diskgroup_rows[0].total_mb == 301989888
    assert diskgroup_rows[0].free_mb == 124454028
    assert diskgroup_rows[0].usable_file_mb == 41474256
    assert diskgroup_rows[0].free_pct == 41.21
    assert diskgroup_rows[0].usable_pct == 13.73
    assert diskgroup_rows[0].asmcmd_stdout == ""
    assert diskgroup_rows[1].total_mb == 75497472
    assert diskgroup_rows[1].free_mb == 48650676
    assert diskgroup_rows[1].usable_file_mb == 16206624
    assert [row.diskgroup_name for row in diskgroup_rows] == ["DATAC1", "RECOC1"]
    assert diskgroup_rows[0].total_mb == 301989888
    assert diskgroup_rows[0].free_mb == 124454028
    assert diskgroup_rows[0].usable_file_mb == 41474256
    assert diskgroup_rows[1].total_mb == 75497472
    assert diskgroup_rows[1].free_mb == 48650676
    assert diskgroup_rows[1].usable_file_mb == 16206624
    assert "awk -F:" in runner.commands[0]
    assert "ps -eo user,args" in runner.commands[1]
    assert runner.commands[2] == (
        "sudo -n -u grid env ORACLE_HOME=/u01/app/23.0.0.0/grid "
        "ORACLE_SID=+ASM1 PATH=/u01/app/23.0.0.0/grid/bin:/usr/bin:/bin "
        "timeout 30s asmcmd lsdg"
    )


def test_direct_command_collection_failed_env() -> None:
    runner = _Runner([
        SimpleNamespace(ok=True, stdout="", stderr="", error=None, returncode=0),
        SimpleNamespace(ok=True, stdout="", stderr="", error=None, returncode=0),
    ])
    collector = ASMDiskgroupCollector(runner)
    rows = collector.collect_host("c1", _host(), __import__('logging').getLogger('t'))
    assert rows[0].asm_collection_status == "failed_env"
    assert rows[0].asm_collection_error == "missing_required_asm_environment"


def test_parse_asmcmd_lsdg_success() -> None:
    from collectors.asm_diskgroups_collector import _parse_lsdg

    sections = {
        "asm_collection_status": "success",
        "asmcmd_stdout": "\n".join(
            [
                "State    Type  Rebal  Sector  Block       AU  Total_MB   Free_MB  Req_mir_free_MB  Usable_file_MB  Offline_disks  Voting_files  Name",
                "MOUNTED  EXTERN N         512   4096  4194304   1000000    120000                0          120000              0             N  DATA/",
            ]
        ),
    }

    rows = _parse_lsdg("c1", "h1", "1.1.1.1", sections)

    assert rows[0].diskgroup_name == "DATA"
    assert rows[0].total_mb == 1000000
    assert rows[0].free_mb == 120000
    assert rows[0].used_pct == 88.0
    assert rows[0].warning_level == "WARNING"
    assert len(rows) == 1
    assert rows[0].asm_collection_status == "success"


def test_parse_exact_captured_asmcmd_stdout_header_aware() -> None:
    from collectors.asm_diskgroups_collector import _parse_lsdg

    asm_stdout = "\n".join(
        [
            "State Type Rebal Sector Logical_Sector Block AU Total_MB Free_MB Req_mir_free_MB Usable_file_MB Offline_disks Voting_files Name",
            "MOUNTED HIGH N 512 512 4096 4194304 544776192 362123424 0 120702048 2 Y DATAC1/",
            "MOUNTED HIGH N 512 512 4096 4194304 944776192 544776192 0 181592064 2 N RECOC1/",
        ]
    )
    sections = {
        "asm_env": "grid_home\t/u01/app/19.0.0/grid\ngrid_owner\tgrid\nasm_sid\t+ASM1\nasmcmd_path\t/u01/app/19.0.0/grid/bin/asmcmd",
        "asm_collection_status": "success",
        "asmcmd_stdout": asm_stdout,
    }

    rows = _parse_lsdg("c1", "h1", "1.1.1.1", sections)

    assert [row.diskgroup_name for row in rows] == ["DATAC1", "RECOC1"]
    assert rows[0].total_mb == 544776192
    assert rows[0].free_mb == 362123424
    assert rows[0].usable_file_mb == 120702048
    assert rows[0].used_pct == 33.53
    assert rows[0].grid_home == "/u01/app/19.0.0/grid"
    assert rows[0].grid_owner == "grid"
    assert rows[0].asm_sid == "+ASM1"
    assert rows[0].asmcmd_path == "/u01/app/19.0.0/grid/bin/asmcmd"
    assert rows[1].total_mb == 944776192
    assert rows[1].free_mb == 544776192
    assert rows[1].used_pct == 42.34


def test_parse_sqlplus_fallback_success() -> None:
    from collectors.asm_diskgroups_collector import _parse_lsdg

    sections = {
        "asm_collection_status": "success",
        "asm_collection_error": "asmcmd_failed_sqlplus_succeeded",
        "asmcmd_stdout": "",
        "sqlplus_stdout": "DATA|MOUNTED|EXTERN|1000000|120000|120000",
    }

    rows = _parse_lsdg("c1", "h1", "1.1.1.1", sections)

    assert rows[0].diskgroup_name == "DATA"
    assert rows[0].state == "MOUNTED"
    assert rows[0].type == "EXTERN"
    assert rows[0].total_mb == 1000000
    assert len(rows) == 1
    assert rows[0].asm_collection_status == "success"
    assert rows[-1].asm_collection_error == ""


def test_missing_grid_home_asm_sid_or_grid_owner_returns_failed_env() -> None:
    from collectors.asm_diskgroups_collector import _parse_lsdg

    sections = {
        "asm_env": "grid_home\t\ngrid_owner\t\nasm_sid\t",
        "asm_collection_status": "failed_env",
        "asm_collection_error": "missing_required_asm_environment",
        "asm_error": "missing ASM_SID from PMON; missing GRID_HOME from /etc/oratab; missing GRID_OWNER from GRID_HOME binaries",
    }

    rows = _parse_lsdg("c1", "h1", "1.1.1.1", sections)

    assert rows == []


def test_build_asmcmd_command_uses_sudo_n_direct_command() -> None:
    from collectors.asm_diskgroups_collector import _build_asmcmd_command

    assert _build_asmcmd_command("grid", "/u01/app/23.0.0.0/grid", "+ASM1", 30) == (
        "sudo -n -u grid env ORACLE_HOME=/u01/app/23.0.0.0/grid "
        "ORACLE_SID=+ASM1 PATH=/u01/app/23.0.0.0/grid/bin:/usr/bin:/bin "
        "timeout 30s asmcmd lsdg"
    )


def test_parse_sections_strips_bash_prompt_and_ignores_unmarked_echo():
    from collectors.asm_diskgroups_collector import _parse_sections

    output = (
        "bash-4.4# set -euo pipefail\n"
        "bash-4.4# ===BEGIN_SECTION:asmcmd_stdout===\n"
        "bash-4.4# State Type Rebal Sector Block AU Total_MB Free_MB Req_mir_free_MB Usable_file_MB Offline_disks Voting_files Name\n"
        "MOUNTED EXTERN N 512 4096 4194304 1000000 120000 0 120000 0 N DATA/\n"
        "bash-4.4# ===END_SECTION:asmcmd_stdout===\n"
        "bash-4.4# outside ignored\n"
    )

    sections = _parse_sections(output)

    assert sections["asmcmd_stdout"].splitlines() == [
        "State Type Rebal Sector Block AU Total_MB Free_MB Req_mir_free_MB Usable_file_MB Offline_disks Voting_files Name",
        "MOUNTED EXTERN N 512 4096 4194304 1000000 120000 0 120000 0 N DATA/",
    ]
