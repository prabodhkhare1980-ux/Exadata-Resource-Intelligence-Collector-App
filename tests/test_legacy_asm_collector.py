import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from types import SimpleNamespace

from collectors.asm_diskgroups_collector import ASMDiskgroupCollector


class _Runner:
    def __init__(self, stdout: str, ok: bool = True):
        self._stdout = stdout
        self._ok = ok

    def run_script(self, host, script):
        return SimpleNamespace(ok=self._ok, stdout=self._stdout, stderr="", error=None, returncode=0)


def _host():
    return SimpleNamespace(name="h1", address="1.1.1.1")


def test_failed_status_from_sections() -> None:
    out = "\n__ERIC_SECTION__:asm_lsdg\nORA-01017\n__ERIC_SECTION__:asm_collection_status\nfailed\n__ERIC_SECTION__:asm_error\nORA-01017\n"
    collector = ASMDiskgroupCollector(_Runner(out))
    rows = collector.collect_host("c1", _host(), __import__('logging').getLogger('t'))
    assert rows == []


def test_script_disables_errexit_around_asm_cmd() -> None:
    from collectors.asm_diskgroups_collector import ASM_COLLECTION_SCRIPT

    assert "set +e" in ASM_COLLECTION_SCRIPT
    assert "asm_rc=$?" in ASM_COLLECTION_SCRIPT
    assert "set -e" in ASM_COLLECTION_SCRIPT


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
    assert rows[-1].asm_collection_error == "asmcmd_failed_sqlplus_succeeded"


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


def test_current_user_equal_grid_owner_branch_does_not_use_sudo() -> None:
    from collectors.asm_diskgroups_collector import ASM_COLLECTION_SCRIPT

    assert 'if [ "$current_user" = "$GRID_OWNER" ]; then\n    env ORACLE_HOME="$GRID_HOME"' in ASM_COLLECTION_SCRIPT
    assert 'asm_command="env ORACLE_HOME=\\"$GRID_HOME\\"' in ASM_COLLECTION_SCRIPT


def test_current_user_differs_from_grid_owner_branch_uses_sudo_n() -> None:
    from collectors.asm_diskgroups_collector import ASM_COLLECTION_SCRIPT

    assert 'sudo -n -u "$GRID_OWNER" env ORACLE_HOME="$GRID_HOME"' in ASM_COLLECTION_SCRIPT
    assert "/[a]sm_pmon/" in ASM_COLLECTION_SCRIPT
    assert "/[o]hasd/" in ASM_COLLECTION_SCRIPT
    assert "stat -c '%U'" not in ASM_COLLECTION_SCRIPT
    assert 'asm_command="sudo -n -u \\"$GRID_OWNER\\" env ORACLE_HOME=\\"$GRID_HOME\\"' in ASM_COLLECTION_SCRIPT


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
