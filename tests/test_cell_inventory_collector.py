"""Tests for the multi-access-model Exadata cell inventory collector."""

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from collectors.cell_inventory_collector import (
    CELL_INVENTORY_COLUMNS,
    CELL_INVENTORY_ERROR_COLUMNS,
    CellInventoryCollector,
    build_crsctl_cluster_name_command,
    build_dcli_cellcli_command,
    build_direct_ssh_cellcli_command,
    build_exacli_command,
    looks_like_cellip_ora,
    parse_cell_group_hosts,
    parse_cell_ips,
    parse_cell_size_gb,
    parse_cellcli_detail,
    parse_cellcli_detail_multi,
    parse_cellip_ora,
    parse_cluster_name,
    parse_command_v,
    parse_dcli_detail,
)
from inventory import CellAccessConfig
from reports.writers import (
    write_cell_inventory_csv,
    write_cell_inventory_errors_csv,
    write_cell_inventory_errors_json,
    write_cell_inventory_json,
)
from ssh_runner import CommandResult


class FakeHost:
    name = "db01"
    address = "db01.example.com"
    force_tty = False
    environment = "onprem"


class FakeCluster:
    name = "rac01"
    environment = "onprem"


def _result(stdout="", stderr="", returncode=0, timed_out=False) -> CommandResult:
    return CommandResult(FakeHost(), [], stdout, stderr, returncode, timed_out)


# Sample cellcli/exacli single-cell detail (no host prefix).
CELL_DETAIL_SINGLE = """name:            cel01
cellVersion:         OSS_23.1.0.0.0_LINUX.X64_240101
releaseVersion:      23.1.0.0.0
makeModel:           Oracle Corporation SUN SERVER X9-2L High Capacity
status:              online
cpuCount:            32
"""

FLASH_DETAIL_SINGLE = """name:            cel01_FLASHCACHE
size:                5.82105T
flashCacheMode:      WriteBack
status:              normal
"""

PHYSICALDISK_DETAIL_SINGLE = """name:            20:0
physicalSize:        10T
diskType:            HardDisk
name:            20:1
physicalSize:        10T
diskType:            HardDisk
name:            FLASH_1_1
physicalSize:        6.4T
diskType:            FlashDisk
"""

# dcli multi-cell variants (host-prefixed).
CELL_DETAIL_DCLI = """cel01: name:            cel01
cel01: cellVersion:         OSS_23.1.0.0.0_LINUX.X64_240101
cel01: releaseVersion:      23.1.0.0.0
cel01: makeModel:           Oracle Corporation SUN SERVER X9-2L High Capacity
cel01: status:              online
cel01: cpuCount:            32
cel02: name:            cel02
cel02: cellVersion:         OSS_23.1.0.0.0_LINUX.X64_240101
cel02: releaseVersion:      23.1.0.0.0
cel02: makeModel:           Oracle Corporation SUN SERVER X9-2L High Capacity
cel02: status:              online
cel02: cpuCount:            32
"""


def _onprem_access(method="dcli_or_direct", users=("celladmin", "root")):
    return CellAccessConfig(
        enabled=True,
        method=method,
        users=tuple(users),
        cell_group_files=("/root/cell_group",),
        allow_direct_cell_ssh=True,
        timeout_seconds=45,
    )


def _exacli_access():
    return CellAccessConfig(
        enabled=True,
        method="exacli",
        cell_ip_file="/etc/oracle/cell/network-config/cellip.ora",
        exacli_user_template="cloud_user_{cluster_name}",
        use_cookie_jar=True,
        no_prompt=True,
        timeout_seconds=45,
    )


# ---------------------------------------------------------------------------
# Pure parsers / builders
# ---------------------------------------------------------------------------


def test_parse_command_v() -> None:
    assert parse_command_v("/usr/bin/dcli\n") == "/usr/bin/dcli"
    assert parse_command_v("") == ""


def test_parse_cluster_name_from_crs6724() -> None:
    assert parse_cluster_name("CRS-6724: Current cluster name is exacs-cl01\n") == "exacs-cl01"


def test_parse_cluster_name_strips_oracle_single_quotes() -> None:
    """ExaCS regression: crsctl wraps the name in single quotes on some versions."""

    # Real ExaCS output that caused cloud_user_'iad3dx02v1' to be issued.
    assert (
        parse_cluster_name("CRS-6724: Current cluster name is 'iad3dx02v1'\n")
        == "iad3dx02v1"
    )
    assert parse_cluster_name("'iad3dx02v1'\n") == "iad3dx02v1"
    assert parse_cluster_name('"clname"\n') == "clname"


def test_parse_cell_ips_from_cellip_ora() -> None:
    text = 'cell="192.168.136.5";cell="192.168.136.6"\n'
    assert parse_cell_ips(text) == ["192.168.136.5", "192.168.136.6"]


def test_parse_cell_group_hosts() -> None:
    assert parse_cell_group_hosts("# comment\ncel01\ncel02\ncel01\n") == ["cel01", "cel02"]


def test_looks_like_cellip_ora_detects_real_format() -> None:
    cellip = 'cell="30.117.250.15;30.117.250.16"\ncell="30.117.250.17;30.117.250.18"\n'
    assert looks_like_cellip_ora(cellip) is True
    assert looks_like_cellip_ora("cel01\ncel02\n") is False  # plain dcli group file


def test_parse_cellip_ora_groups_redundant_ips_per_cell() -> None:
    cellip = (
        'cell="30.117.250.15;30.117.250.16"\n'
        'cell="30.117.250.17;30.117.250.18"\n'
        'cell="30.117.250.19;30.117.250.20"\n'
    )
    cells = parse_cellip_ora(cellip)
    # 3 cells, each with its two redundant IPs (not 6 separate cells).
    assert cells == [
        ["30.117.250.15", "30.117.250.16"],
        ["30.117.250.17", "30.117.250.18"],
        ["30.117.250.19", "30.117.250.20"],
    ]


def test_parse_cellcli_detail_single_cell() -> None:
    attrs = parse_cellcli_detail(CELL_DETAIL_SINGLE)
    assert attrs["name"] == "cel01"
    assert attrs["releaseVersion"] == "23.1.0.0.0"
    assert attrs["makeModel"].endswith("High Capacity")


def test_parse_cellcli_detail_multi_splits_on_name() -> None:
    objs = parse_cellcli_detail_multi(PHYSICALDISK_DETAIL_SINGLE)
    assert len(objs) == 3
    assert objs[2]["diskType"] == "FlashDisk"


def test_parse_dcli_detail_groups_by_cell() -> None:
    parsed = parse_dcli_detail(CELL_DETAIL_DCLI)
    assert set(parsed) == {"cel01", "cel02"}
    assert parsed["cel01"]["releaseVersion"] == "23.1.0.0.0"


def test_parse_cell_size_gb_units() -> None:
    assert parse_cell_size_gb("5.82105T") == round(5.82105 * 1024, 2)
    assert parse_cell_size_gb("745.211G") == 745.21
    assert parse_cell_size_gb("garbage") is None


def test_method_inferred_from_env_name(tmp_path) -> None:
    """oci-style env names default to exacli; explicit method still wins."""

    from inventory import load_inventory

    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        """
environments:
  onprem:
    ssh_user: srcordma
    auth: {method: ssh_key, private_key: .secrets/ssh/k}
    privilege: {enabled: true, method: sudo, sudo_password: none, force_tty: true}
  oci:
    description: OCI Exadata estate
    ssh_user: srcordma
    auth: {method: ssh_key, private_key: .secrets/ssh/k}
    privilege: {enabled: true, method: sudo, sudo_password: none, force_tty: true}
  exacs-prod:
    ssh_user: srcordma
    auth: {method: ssh_key, private_key: .secrets/ssh/k}
    privilege: {enabled: true, method: sudo, sudo_password: none, force_tty: true}
  legacy-with-override:
    description: weird mixed env
    ssh_user: srcordma
    auth: {method: ssh_key, private_key: .secrets/ssh/k}
    privilege: {enabled: true, method: sudo, sudo_password: none, force_tty: true}
    cell_access: {method: exacli}
clusters:
  - {name: c1, environment: onprem, hosts: [{name: h1, address: 10.0.0.1}]}
  - {name: c2, environment: oci, hosts: [{name: h2, address: 10.0.0.2}]}
  - {name: c3, environment: exacs-prod, hosts: [{name: h3, address: 10.0.0.3}]}
  - {name: c4, environment: legacy-with-override, hosts: [{name: h4, address: 10.0.0.4}]}
collection:
  cell_inventory: {enabled: true}
""",
        encoding="utf-8",
    )
    inv = load_inventory(str(cfg))
    assert inv.cell_access_by_environment["onprem"].method == "dcli_or_direct"
    # Inferred from env name "oci" / "exacs-prod".
    assert inv.cell_access_by_environment["oci"].method == "exacli"
    assert inv.cell_access_by_environment["exacs-prod"].method == "exacli"
    # Explicit method overrides the inference.
    assert inv.cell_access_by_environment["legacy-with-override"].method == "exacli"


def test_command_builders() -> None:
    assert "dcli -g /root/cell_group -l celladmin" in build_dcli_cellcli_command(
        "/root/cell_group", "celladmin", "list cell detail"
    )
    assert "ssh" in build_direct_ssh_cellcli_command("cel01", "root", "list cell detail")
    assert "BatchMode=yes" in build_direct_ssh_cellcli_command("cel01", "root", "list cell detail")
    exacli = build_exacli_command("/usr/bin/exacli", "cloud_user_x", "1.2.3.4", "list cell detail")
    assert "exacli -l cloud_user_x -c 1.2.3.4 --cookie-jar -n -e" in exacli
    assert "crsctl get cluster name" in build_crsctl_cluster_name_command("/u01/grid", "grid")


def test_cookie_refresh_command_pipes_password_via_stdin_only() -> None:
    """The password must arrive at exacli via stdin, never on argv or env."""

    from collectors.cell_inventory_collector import build_exacli_cookie_refresh_command

    cmd = build_exacli_cookie_refresh_command(
        "/usr/bin/exacli", "cloud_user_xx", "1.2.3.4",
        password_command="/opt/oracle/get_cloud_user_password.sh",
        timeout_seconds=60,
    )
    # Outer scaffolding: timeout-bounded bash -c.
    assert cmd.startswith("timeout 60s bash -c ")
    # Password command is invoked inside a subshell into a shell variable.
    assert "_p=$( /opt/oracle/get_cloud_user_password.sh )" in cmd
    # The password is piped to exacli on stdin, never on argv.
    assert "$_p" in cmd
    assert "| /usr/bin/exacli -l cloud_user_xx -c 1.2.3.4" in cmd
    # The refresh call uses --cookie-jar but NOT -n (otherwise exacli would
    # refuse to read the password from stdin).
    assert "--cookie-jar" in cmd
    assert "--cookie-jar -e" in cmd  # i.e. no '-n' between --cookie-jar and -e
    # Subshell var is unset and a sentinel printed on success.
    assert "unset _p" in cmd
    assert "COOKIE_REFRESH_OK" in cmd


def test_cookie_probe_command_is_cheap_and_noninteractive() -> None:
    from collectors.cell_inventory_collector import build_exacli_probe_command

    probe = build_exacli_probe_command("/usr/bin/exacli", "cloud_user_xx", "1.2.3.4")
    assert "-n" in probe  # non-interactive
    assert "-e 'list cell'" in probe  # cheap call


def test_exacli_auto_refreshes_cookie_when_expired_then_succeeds() -> None:
    """Probe fails auth → refresh runs → cell collection succeeds."""

    state = {"refreshed": False}

    def runner(cmd: str) -> CommandResult:
        if "crsctl get cluster name" in cmd:
            return _result("CRS-6724: Current cluster name is exacs-cl01\n")
        if "cat /etc/oracle/cell/network-config/cellip.ora" in cmd:
            return _result('cell="192.168.136.5;192.168.136.6"\n')
        if "command -v exacli" in cmd:
            return _result("/usr/bin/exacli\n")
        # Probe path: "list cell" (the cheap probe). Before refresh -> auth fail.
        if "-e 'list cell'" in cmd and "list cell detail" not in cmd:
            if not state["refreshed"]:
                return _result(stderr="Authentication required: cookie expired", returncode=1)
            return _result("name: cel01\n", returncode=0)
        # Refresh pipeline.
        if "COOKIE_REFRESH_OK" in cmd:
            state["refreshed"] = True
            return _result("COOKIE_REFRESH_OK\n", returncode=0)
        # Real per-cell calls now succeed because the cookie is fresh.
        if "list cell detail" in cmd:
            return _result(CELL_DETAIL_SINGLE)
        if "list flashcache detail" in cmd:
            return _result(FLASH_DETAIL_SINGLE)
        if "list physicaldisk detail" in cmd:
            return _result(PHYSICALDISK_DETAIL_SINGLE)
        return _result("")

    access = CellAccessConfig(
        enabled=True, method="exacli",
        cell_ip_file="/etc/oracle/cell/network-config/cellip.ora",
        exacli_user_template="cloud_user_{cluster_name}",
        use_cookie_jar=True, no_prompt=True, timeout_seconds=45,
        cookie_refresh=True, password_command="/opt/oracle/get_pwd.sh",
    )
    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), access,
        grid_home="/u01/app/19/grid", grid_owner="grid", command_runner=runner,
    )
    assert state["refreshed"] is True
    assert len(records) == 1
    assert records[0].collection_status == "success"


def test_exacli_skips_refresh_when_probe_already_succeeds() -> None:
    """Cookie still valid → password_command must NOT be invoked."""

    pw_calls = []

    def runner(cmd: str) -> CommandResult:
        if "crsctl get cluster name" in cmd:
            return _result("CRS-6724: Current cluster name is exacs-cl01\n")
        if "cellip.ora" in cmd:
            return _result('cell="192.168.136.5;192.168.136.6"\n')
        if "command -v exacli" in cmd:
            return _result("/usr/bin/exacli\n")
        if "/opt/oracle/get_pwd.sh" in cmd:
            pw_calls.append(cmd)
            return _result("topsecret\n")
        if "-e 'list cell'" in cmd and "list cell detail" not in cmd:
            return _result("name: cel01\n")
        if "list cell detail" in cmd:
            return _result(CELL_DETAIL_SINGLE)
        if "list flashcache detail" in cmd:
            return _result(FLASH_DETAIL_SINGLE)
        if "list physicaldisk detail" in cmd:
            return _result(PHYSICALDISK_DETAIL_SINGLE)
        return _result("")

    access = CellAccessConfig(
        enabled=True, method="exacli",
        cell_ip_file="/etc/oracle/cell/network-config/cellip.ora",
        exacli_user_template="cloud_user_{cluster_name}",
        cookie_refresh=True, password_command="/opt/oracle/get_pwd.sh",
        use_cookie_jar=True, no_prompt=True, timeout_seconds=45,
    )
    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), access,
        grid_home="/u01/app/19/grid", grid_owner="grid", command_runner=runner,
    )
    assert records[0].collection_status == "success"
    assert pw_calls == []  # password retrieval never happened


def test_exacli_refresh_surfaces_clear_password_command_failure() -> None:
    def runner(cmd: str) -> CommandResult:
        if "crsctl get cluster name" in cmd:
            return _result("CRS-6724: Current cluster name is exacs-cl01\n")
        if "cellip.ora" in cmd:
            return _result('cell="192.168.136.5;192.168.136.6"\n')
        if "command -v exacli" in cmd:
            return _result("/usr/bin/exacli\n")
        # Probe: auth required.
        if "-e 'list cell'" in cmd and "list cell detail" not in cmd:
            return _result(stderr="Authentication required: cookie expired", returncode=1)
        # Refresh: password_command failure path (exit 81 from our wrapper).
        if "COOKIE_REFRESH_OK" in cmd:
            return _result(stderr="bad script", returncode=81)
        if "list cell detail" in cmd:
            return _result(stderr="Authentication required", returncode=1)
        return _result("")

    access = CellAccessConfig(
        enabled=True, method="exacli",
        cell_ip_file="/etc/oracle/cell/network-config/cellip.ora",
        cookie_refresh=True, password_command="/bad/script",
        timeout_seconds=45,
    )
    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), access,
        grid_home="/u01/app/19/grid", grid_owner="grid", command_runner=runner,
    )
    assert records[0].collection_status == "failed"
    assert records[0].error_category == "EXACLI_AUTH_REQUIRED"
    # Diagnostic explains why refresh did not help.
    assert "password_command_failed" in records[0].collection_error


# ---------------------------------------------------------------------------
# dcli flow (on-prem)
# ---------------------------------------------------------------------------


def test_dcli_success_multi_cell() -> None:
    def runner(cmd: str) -> CommandResult:
        if "command -v dcli" in cmd:
            return _result("/usr/bin/dcli\n")
        if "cat /root/cell_group" in cmd:
            return _result("cel01\ncel02\n")
        if "list cell detail" in cmd:
            return _result(CELL_DETAIL_DCLI)
        if "list flashcache detail" in cmd:
            return _result("cel01: name: cel01_FC\ncel01: size: 5.82105T\ncel02: name: cel02_FC\ncel02: size: 5.82105T\n")
        if "list physicaldisk detail" in cmd:
            return _result(
                "cel01: name: 20:0\ncel01: physicalSize: 10T\ncel01: diskType: HardDisk\n"
                "cel02: name: 20:0\ncel02: physicalSize: 10T\ncel02: diskType: HardDisk\n"
            )
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _onprem_access(), command_runner=runner
    )
    assert len(records) == 2
    cel01 = next(r for r in records if r.CELL_NAME == "cel01")
    assert cel01.collection_status == "success"
    assert cel01.cell_access_method == "dcli"
    assert cel01.cell_user == "celladmin"
    assert cel01.CELL_RELEASE_VERSION == "23.1.0.0.0"
    assert float(cel01.FLASH_CACHE_GB) == round(5.82105 * 1024, 2)
    assert cel01.HARD_DISK_COUNT == "1"


def test_dcli_auth_fails_falls_back_to_root() -> None:
    seen_users = []

    def runner(cmd: str) -> CommandResult:
        if "command -v dcli" in cmd:
            return _result("/usr/bin/dcli\n")
        if "cat /root/cell_group" in cmd:
            return _result("cel01\n")
        if "-l celladmin" in cmd:
            seen_users.append("celladmin")
            return _result(stderr="Permission denied (publickey).", returncode=255)
        if "-l root" in cmd:
            seen_users.append("root")
            if "list cell detail" in cmd:
                return _result(CELL_DETAIL_DCLI.replace("cel02", "celX").split("cel02")[0])
            return _result("")
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _onprem_access(), command_runner=runner
    )
    assert "celladmin" in seen_users and "root" in seen_users
    assert records[0].collection_status == "success"
    assert records[0].cell_user == "root"


# ---------------------------------------------------------------------------
# direct SSH flow (no dcli)
# ---------------------------------------------------------------------------


def test_direct_ssh_when_dcli_absent() -> None:
    def runner(cmd: str) -> CommandResult:
        if "command -v dcli" in cmd:
            return _result("")  # dcli not present
        if "cat /root/cell_group" in cmd:
            return _result("cel01\n")
        if cmd.startswith("timeout") and "ssh" in cmd:
            if "list cell detail" in cmd:
                return _result(CELL_DETAIL_SINGLE)
            if "list flashcache detail" in cmd:
                return _result(FLASH_DETAIL_SINGLE)
            if "list physicaldisk detail" in cmd:
                return _result(PHYSICALDISK_DETAIL_SINGLE)
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _onprem_access(), command_runner=runner
    )
    assert len(records) == 1
    rec = records[0]
    assert rec.collection_status == "success"
    assert rec.cell_access_method == "direct_ssh"
    assert rec.dcli_available == "false"
    assert float(rec.HARD_DISK_GB) == round(20 * 1024, 2)
    assert rec.FLASH_DISK_COUNT == "1"


def test_cellip_ora_uses_direct_ssh_not_dcli_g() -> None:
    """Regression: cellip.ora must NOT be passed to `dcli -g`.

    Reproduces the field bug where dcli treated each cell="ip;ip" line as a
    hostname. With the fix, each line is one cell reached by direct SSH to
    one of its redundant IPs.
    """

    commands_seen = []

    def runner(cmd: str) -> CommandResult:
        commands_seen.append(cmd)
        if "command -v dcli" in cmd:
            return _result("/usr/bin/dcli\n")
        if "cat /etc/oracle/cell/network-config/cellip.ora" in cmd:
            return _result(
                'cell="30.117.250.15;30.117.250.16"\n'
                'cell="30.117.250.17;30.117.250.18"\n'
            )
        # other cell_group_files absent
        if "cat /root/cell_group" in cmd:
            return _result("", returncode=1)
        if "list cell detail" in cmd:
            return _result(CELL_DETAIL_SINGLE)
        if "list flashcache detail" in cmd:
            return _result(FLASH_DETAIL_SINGLE)
        if "list physicaldisk detail" in cmd:
            return _result(PHYSICALDISK_DETAIL_SINGLE)
        return _result("")

    access = CellAccessConfig(
        enabled=True, method="dcli_or_direct", users=("root",),
        cell_group_files=("/root/cell_group", "/etc/oracle/cell/network-config/cellip.ora"),
        allow_direct_cell_ssh=True, timeout_seconds=45,
    )
    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(FakeCluster(), FakeHost(), access, command_runner=runner)

    # Two cells (one per cellip.ora line), reached by direct SSH.
    assert len(records) == 2
    assert all(r.collection_status == "success" for r in records)
    assert all(r.cell_access_method == "direct_ssh" for r in records)
    assert {r.cell_target for r in records} == {"30.117.250.15", "30.117.250.17"}
    # cellip.ora was never handed to `dcli -g`.
    assert not any("dcli -g /etc/oracle/cell/network-config/cellip.ora" in c for c in commands_seen)
    # And the nested ssh is wrapped in sudo -n by default.
    assert any("sudo -n ssh" in c and "30.117.250.15" in c for c in commands_seen)


def test_direct_ssh_falls_back_to_second_redundant_ip() -> None:
    def runner(cmd: str) -> CommandResult:
        if "command -v dcli" in cmd:
            return _result("")  # no dcli
        if "cat /etc/oracle/cell/network-config/cellip.ora" in cmd:
            return _result('cell="30.117.250.15;30.117.250.16"\n')
        if "/root/cell_group" in cmd:
            return _result("", returncode=1)
        # First IP unreachable, second IP works.
        if "30.117.250.15" in cmd:
            return _result(stderr="ssh: connect to host 30.117.250.15 port 22: No route to host", returncode=255)
        if "30.117.250.16" in cmd and "list cell detail" in cmd:
            return _result(CELL_DETAIL_SINGLE)
        if "30.117.250.16" in cmd:
            return _result("")
        return _result("")

    access = CellAccessConfig(
        enabled=True, method="dcli_or_direct", users=("root",),
        cell_group_files=("/etc/oracle/cell/network-config/cellip.ora",),
        allow_direct_cell_ssh=True, timeout_seconds=45,
    )
    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(FakeCluster(), FakeHost(), access, command_runner=runner)
    assert len(records) == 1
    assert records[0].collection_status == "success"
    assert records[0].cell_target == "30.117.250.16"  # fell back to the redundant IP


def test_connection_closed_not_classified_as_dcli_not_found() -> None:
    # dcli IS present but the cell command fails with connection noise.
    def runner(cmd: str) -> CommandResult:
        if "command -v dcli" in cmd:
            return _result("/usr/bin/dcli\n")
        if "cat /root/cell_group" in cmd:
            return _result("cel01\n")
        if "list cell detail" in cmd:
            return _result(stderr="Connection to cel01 closed.", returncode=255)
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _onprem_access(users=("celladmin",)), command_runner=runner
    )
    assert records[0].collection_status == "failed"
    assert records[0].error_category != "DCLI_NOT_FOUND"
    assert records[0].error_category == "CELL_COMMAND_FAILED"
    assert "Connection to cel01 closed" in records[0].raw_error


def test_dcli_missing_and_no_cells_reports_dcli_not_found() -> None:
    def runner(cmd: str) -> CommandResult:
        if "command -v dcli" in cmd:
            return _result("")
        # no cell group, no /etc/hosts cells
        return _result("", returncode=1)

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _onprem_access(), command_runner=runner
    )
    assert records[0].collection_status == "failed"
    assert records[0].error_category == "DCLI_NOT_FOUND"


# ---------------------------------------------------------------------------
# ExaCLI flow (OCI)
# ---------------------------------------------------------------------------


def test_exacli_success() -> None:
    def runner(cmd: str) -> CommandResult:
        if "crsctl get cluster name" in cmd:
            return _result("CRS-6724: Current cluster name is exacs-cl01\n")
        if "cat /etc/oracle/cell/network-config/cellip.ora" in cmd:
            return _result('cell="192.168.136.5;192.168.136.6"\ncell="192.168.136.7;192.168.136.8"\n')
        if "list cell detail" in cmd:
            return _result(CELL_DETAIL_SINGLE)
        if "list flashcache detail" in cmd:
            return _result(FLASH_DETAIL_SINGLE)
        if "list physicaldisk detail" in cmd:
            return _result(PHYSICALDISK_DETAIL_SINGLE)
        if "command -v exacli" in cmd:
            return _result("/usr/local/bin/exacli\n")
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _exacli_access(),
        grid_home="/u01/app/19/grid", grid_owner="grid", command_runner=runner,
    )
    assert len(records) == 2  # two cells (one record per cellip.ora line)
    rec = records[0]
    assert rec.collection_status == "success"
    assert rec.cell_access_method == "exacli"
    assert rec.cell_user == "cloud_user_exacs-cl01"
    # Primary (first) IP of each cell is used.
    assert {r.cell_target for r in records} == {"192.168.136.5", "192.168.136.7"}


def test_exacli_storage_user_is_bare_when_crsctl_quotes_cluster_name() -> None:
    """Regression: ExaCS crsctl output `... name is 'clname'` must NOT yield
    cloud_user_'clname' as the storage user."""

    seen_commands = []

    def runner(cmd: str) -> CommandResult:
        seen_commands.append(cmd)
        if "crsctl get cluster name" in cmd:
            return _result("CRS-6724: Current cluster name is 'iad3dx02v1'\n")
        if "cat /etc/oracle/cell/network-config/cellip.ora" in cmd:
            return _result('cell="100.106.2.233;100.106.2.234"\n')
        if "list cell detail" in cmd:
            return _result(CELL_DETAIL_SINGLE)
        if "list flashcache detail" in cmd:
            return _result(FLASH_DETAIL_SINGLE)
        if "list physicaldisk detail" in cmd:
            return _result(PHYSICALDISK_DETAIL_SINGLE)
        if "command -v exacli" in cmd:
            return _result("/usr/local/bin/exacli\n")
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _exacli_access(),
        grid_home="/u01/app/19/grid", grid_owner="grid", command_runner=runner,
    )
    assert records[0].collection_status == "success"
    # The storage user must NOT contain literal quotes.
    assert records[0].cell_user == "cloud_user_iad3dx02v1"
    # And no exacli call should have been issued with a quoted username.
    assert not any("cloud_user_'iad3dx02v1'" in c for c in seen_commands)


def test_exacli_refuses_cluster_name_with_stray_quote() -> None:
    """If a future Oracle version embeds quotes in the middle of the name,
    fail loudly rather than silently issue a broken storage user."""

    def runner(cmd: str) -> CommandResult:
        if "crsctl get cluster name" in cmd:
            # Pathological: a stray quote inside the bare-name fallback path.
            return _result("CRS-6724: Current cluster name is bad'name\n")
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _exacli_access(),
        grid_home="/u01/app/19/grid", grid_owner="grid", command_runner=runner,
    )
    assert records[0].collection_status == "failed"
    assert records[0].error_category == "CELL_COMMAND_FAILED"
    assert "stray characters" in records[0].collection_error


def test_exacli_auth_required() -> None:
    def runner(cmd: str) -> CommandResult:
        if "crsctl get cluster name" in cmd:
            return _result("CRS-6724: Current cluster name is exacs-cl01\n")
        if "cellip.ora" in cmd:
            return _result('cell="192.168.136.5"\n')
        if "list cell detail" in cmd:
            return _result(stderr="Password cookie not found; authentication required", returncode=1)
        if "command -v exacli" in cmd:
            return _result("/usr/local/bin/exacli\n")
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _exacli_access(),
        grid_home="/u01/app/19/grid", grid_owner="grid", command_runner=runner,
    )
    assert records[0].collection_status == "failed"
    assert records[0].error_category == "EXACLI_AUTH_REQUIRED"
    assert "exacli" in records[0].collection_error.lower()
    assert "cookie" in records[0].collection_error.lower()


def test_exacli_not_found() -> None:
    def runner(cmd: str) -> CommandResult:
        if "crsctl get cluster name" in cmd:
            return _result("CRS-6724: Current cluster name is exacs-cl01\n")
        if "cellip.ora" in cmd:
            return _result('cell="192.168.136.5"\n')
        if "command -v exacli" in cmd:
            return _result("")  # exacli absent
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _exacli_access(),
        grid_home="/u01/app/19/grid", grid_owner="grid", command_runner=runner,
    )
    assert records[0].error_category == "EXACLI_NOT_FOUND"


def test_exacli_cell_ip_file_missing() -> None:
    def runner(cmd: str) -> CommandResult:
        if "crsctl get cluster name" in cmd:
            return _result("CRS-6724: Current cluster name is exacs-cl01\n")
        if "cellip.ora" in cmd:
            return _result(stderr="cat: cellip.ora: No such file or directory", returncode=1)
        return _result("")

    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _exacli_access(),
        grid_home="/u01/app/19/grid", grid_owner="grid", command_runner=runner,
    )
    assert records[0].error_category == "CELL_IP_FILE_NOT_FOUND"


def test_exacli_missing_grid_env_reports_command_failed() -> None:
    collector = CellInventoryCollector(runner=None)
    records = collector.collect_cluster(
        FakeCluster(), FakeHost(), _exacli_access(),
        grid_home="", grid_owner="", command_runner=lambda c: _result(""),
    )
    assert records[0].error_category == "CELL_COMMAND_FAILED"


def test_disabled_access_returns_nothing() -> None:
    collector = CellInventoryCollector(runner=None)
    access = CellAccessConfig(enabled=False)
    assert collector.collect_cluster(FakeCluster(), FakeHost(), access, command_runner=lambda c: _result("")) == []


# ---------------------------------------------------------------------------
# Writers (success / errors split)
# ---------------------------------------------------------------------------


def test_writers_split_success_and_errors(tmp_path: Path) -> None:
    def runner(cmd: str) -> CommandResult:
        if "command -v dcli" in cmd:
            return _result("/usr/bin/dcli\n")
        if "cat /root/cell_group" in cmd:
            return _result("cel01\n")
        if "list cell detail" in cmd:
            return _result(CELL_DETAIL_DCLI)
        if "list flashcache detail" in cmd:
            return _result("cel01: name: fc\ncel01: size: 5T\n")
        if "list physicaldisk detail" in cmd:
            return _result("cel01: name: d\ncel01: physicalSize: 10T\ncel01: diskType: HardDisk\n")
        return _result("")

    collector = CellInventoryCollector(runner=None)
    success = collector.collect_cluster(FakeCluster(), FakeHost(), _onprem_access(), command_runner=runner)

    # Build a failed record too.
    def bad_runner(cmd: str) -> CommandResult:
        if "command -v dcli" in cmd:
            return _result("")
        return _result("", returncode=1)

    failed = collector.collect_cluster(FakeCluster(), FakeHost(), _onprem_access(), command_runner=bad_runner)
    all_records = success + failed

    scsv = write_cell_inventory_csv(all_records, tmp_path)
    sjson = write_cell_inventory_json(all_records, tmp_path)
    ecsv = write_cell_inventory_errors_csv(all_records, tmp_path)
    ejson = write_cell_inventory_errors_json(all_records, tmp_path)
    assert all(p.exists() for p in (scsv, sjson, ecsv, ejson))

    success_payload = json.loads(sjson.read_text())
    assert len(success_payload) == 2  # cel01, cel02
    assert set(success_payload[0].keys()) == set(CELL_INVENTORY_COLUMNS)
    assert all(r["collection_status"] == "success" for r in success_payload)

    error_payload = json.loads(ejson.read_text())
    assert len(error_payload) == 1
    assert set(error_payload[0].keys()) == set(CELL_INVENTORY_ERROR_COLUMNS)
    assert error_payload[0]["collection_status"] == "failed"
