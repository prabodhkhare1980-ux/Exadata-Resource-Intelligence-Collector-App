from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from collectors.db_inventory_collector import _parse_database_list, _parse_pmon_sids, _parse_sections


def test_parse_pmon_sid_from_process_name() -> None:
    output = "oracle   1234  1  0 00:00 ?        00:00:00 ora_pmon_DOFLDVPD1\n"
    assert _parse_pmon_sids(output) == ["DOFLDVPD1"]


def test_srvctl_database_list_is_authoritative_and_sanitized() -> None:
    srvctl_output = "DOFLDVPD\ndlorfspd\ndotst1pd\nDOFLDVPD\n\n"
    assert _parse_database_list(srvctl_output) == ["DOFLDVPD", "dlorfspd", "dotst1pd"]


def test_parse_sections_strips_shell_prompt_pollution() -> None:
    output = "__ERIC_SECTION__:hostname\nbash-4.4#\nexample.host\n$\n#\n>\n"
    sections = _parse_sections(output)
    assert sections["hostname"] == "example.host"

from dataclasses import dataclass

from ssh_runner import CommandResult
from collectors.db_inventory_collector import (
    _build_db_resource_sql,
    _collect_db_resource_details,
    _parse_db_resource_sql_output,
    _parse_oracle_home_from_srvctl_config,
    _parse_running_instances_from_srvctl_status,
    _select_local_instance,
)


@dataclass(frozen=True)
class FakeHost:
    name: str = "node1"
    address: str = "10.0.0.1"
    user: str = "srcordma"
    environment: str = "test"
    auth_method: str = "ssh_key"
    private_key: str | None = None
    strict_host_key_checking: str = "no"
    port: int = 22
    privilege_enabled: bool = True
    privilege_method: str = "sudo"
    sudo_password_mode: str = "none"
    force_tty: bool = False
    timeout_seconds: int = 60


def _result(stdout: str = "", stderr: str = "", returncode: int = 0) -> CommandResult:
    return CommandResult(FakeHost(), [], stdout, stderr, returncode)


def test_parse_oracle_home_from_srvctl_config_patterns() -> None:
    assert _parse_oracle_home_from_srvctl_config("Oracle home: /u01/app/oracle/product/19/dbhome_1") == "/u01/app/oracle/product/19/dbhome_1"
    assert _parse_oracle_home_from_srvctl_config("Oracle home is /u01/app/oracle/product/12/dbhome_1") == "/u01/app/oracle/product/12/dbhome_1"
    assert _parse_oracle_home_from_srvctl_config("Database home: /u01/app/oracle/product/11/dbhome_1") == "/u01/app/oracle/product/11/dbhome_1"
    assert _parse_oracle_home_from_srvctl_config("Home: /u01/app/oracle/product/21/dbhome_1") == "/u01/app/oracle/product/21/dbhome_1"


def test_parse_running_instances_from_srvctl_status() -> None:
    text = "Instance DB1_1 is running on node node1\nInstance DB1_2 is not running on node node2\nInstance DB1_3 is running on node node3.example.com"
    assert _parse_running_instances_from_srvctl_status(text) == [
        {"sid": "DB1_1", "node": "node1", "mapping_source": "srvctl_node_match"},
        {"sid": "DB1_3", "node": "node3.example.com", "mapping_source": "srvctl_node_match"},
    ]


def test_select_local_instance_by_hostname_and_single_instance_fallback() -> None:
    instances = [
        {"sid": "DB1_1", "node": "node1"},
        {"sid": "DB1_2", "node": "node2"},
    ]
    assert _select_local_instance(instances, {"inventory_name": "other", "hostname": "node2.example.com"}) == {
        "sid": "DB1_2",
        "node": "node2",
        "mapping_source": "srvctl_node_match",
    }
    assert _select_local_instance([{"sid": "DB1_1", "node": "remote"}], "node1") == {
        "sid": "DB1_1",
        "node": "remote",
        "mapping_source": "single_running_instance",
    }


def test_parse_11g_sql_output_parser() -> None:
    output = "node1|DB11|PRIMARY|READ WRITE|11.2.0.4.0|false|2|8|2|10|4|500|16|1024.12|768.34\n"
    row = _parse_db_resource_sql_output(output)
    assert row["HOST_NAME"] == "node1"
    assert row["VERSION"] == "11.2.0.4.0"
    assert row["RAC_ENABLED"] == "FALSE"
    assert row["USED_DB_SIZE_GB"] == "768.34"


def test_parse_12c_sql_output_parser() -> None:
    output = "\nSQL> ignored\nnode1|CDB1|PRIMARY|READ WRITE|19.20.0.0.0|TRUE|2|16|4|20|8|800|32|2048|1024\n"
    row = _parse_db_resource_sql_output(output)
    assert row["DB_NAME"] == "CDB1"
    assert row["VERSION"] == "19.20.0.0.0"
    assert row["RAC_ENABLED"] == "TRUE"
    assert row["DB_SIZE_GB"] == "2048"


def test_collect_db_resource_details_falls_back_from_cdb_views_to_dba_views() -> None:
    calls: list[bool] = []

    def executor(oracle_home: str, sid: str, sql: str, use_cdb_views: bool) -> CommandResult:
        calls.append(use_cdb_views)
        if use_cdb_views:
            assert "cdb_data_files" in sql
            return _result(stderr="ORA-00942: table or view does not exist", returncode=942)
        assert "dba_data_files" in sql
        return _result(stdout="node1|DB1|PRIMARY|READ WRITE|19.0.0.0.0|true|1|1|2|3|4|300|8|10|5\n")

    rows = _collect_db_resource_details(
        None,
        FakeHost(),
        "c1",
        "node1",
        "10.0.0.1",
        "now",
        ["DB1_UNQ"],
        {"DB1_UNQ": "Oracle home: /u01/dbhome\nVersion: 19.0.0.0.0"},
        {"DB1_UNQ": "Instance DB1 is running on node node1"},
        [],
        "node1.example.com",
        sql_executor=executor,
    )
    assert calls == [True, False]
    assert rows[0]["collection_status"] == "success"
    assert rows[0]["size_source"] == "dba_fallback"
    assert rows[0]["DB_NAME"] == "DB1"


def test_collect_db_resource_details_skips_when_no_local_instance() -> None:
    rows = _collect_db_resource_details(
        None,
        FakeHost(),
        "c1",
        "node1",
        "10.0.0.1",
        "now",
        ["DB1_UNQ"],
        {"DB1_UNQ": "Oracle home: /u01/dbhome"},
        {"DB1_UNQ": "Instance DB1_1 is running on node node2\nInstance DB1_2 is running on node node3"},
        [],
        "node1.example.com",
    )
    assert rows == [
        {
            "HOST_NAME": "",
            "DB_NAME": "",
            "DB_ROLE": "",
            "OPEN_MODE": "",
            "VERSION": "",
            "RAC_ENABLED": "",
            "INST_COUNT": "",
            "SGA_TARGET_GB": "",
            "PGA_AGGR_TARGET_GB": "",
            "SGA_MAX_SIZE_GB": "",
            "PGA_AGGR_LIMIT_GB": "",
            "PROCESSES": "",
            "CPU_COUNT": "",
            "DB_SIZE_GB": "",
            "USED_DB_SIZE_GB": "",
            "Cluster": "c1",
            "cluster": "c1",
            "host": "node1",
            "address": "10.0.0.1",
            "db_unique_name": "DB1_UNQ",
            "oracle_home": "/u01/dbhome",
            "oracle_sid": "",
            "size_source": "",
            "collection_status": "skipped",
            "collection_error": "no_local_running_instance",
            "sql_returncode": "",
            "sql_stderr": "",
            "Collected_At": "now",
        }
    ]


def test_build_db_resource_sql_uses_dba_views_for_11g() -> None:
    sql = _build_db_resource_sql("11.2.0.4.0", use_cdb_views=True)
    assert "dba_data_files" in sql
    assert "cdb_data_files" not in sql

from collectors.db_inventory_collector import (
    DB_INVENTORY_SCRIPT,
    DBInventoryCollector,
    _build_gi_command,
    _collect_pmon_oratab_fallback_details,
)


class FakeRunner:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout

    def run_script(self, host: FakeHost, script: str) -> CommandResult:
        return CommandResult(host, [], self.stdout, "", 0)


class FakeLogger:
    def info(self, *args, **kwargs) -> None:
        pass

    def debug(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def error(self, *args, **kwargs) -> None:
        pass

    def exception(self, *args, **kwargs) -> None:
        pass


def _section(name: str, value: str) -> str:
    return f"\n__ERIC_SECTION__:{name}\n{value}\n"


def test_srvctl_gi_command_runs_as_oracle_on_on_prem() -> None:
    command = _build_gi_command("oracle", "/u01/app/19.0.0.0/grid", "srvctl config database")
    assert command == "sudo -n -u oracle env ORACLE_HOME=/u01/app/19.0.0.0/grid PATH=/u01/app/19.0.0.0/grid/bin:/usr/bin:/bin srvctl config database"


def test_srvctl_gi_command_runs_as_grid_on_oci() -> None:
    command = _build_gi_command("grid", "/u01/app/23.0.0.0/grid", "crsctl stat res -t")
    assert command == "sudo -n -u grid env ORACLE_HOME=/u01/app/23.0.0.0/grid PATH=/u01/app/23.0.0.0/grid/bin:/usr/bin:/bin crsctl stat res -t"


def test_db_inventory_script_discovers_grid_env_and_uses_sudo_gi_owner() -> None:
    assert "awk -F: '/^\\+ASM/ {print $1 \"|\" $2; exit}' /etc/oratab" in DB_INVENTORY_SCRIPT
    assert "stat -c '%U' \"$grid_home/bin/crsctl\"" in DB_INVENTORY_SCRIPT
    assert 'sudo -n -u "$grid_owner" env ORACLE_HOME="$grid_home" PATH="$grid_home/bin:/usr/bin:/bin" "$@"' in DB_INVENTORY_SCRIPT


def test_empty_srvctl_list_marks_partial_and_includes_stderr() -> None:
    stdout = "".join(
        [
            _section("hostname", "node1.example.com"),
            _section("grid_home", "/u01/app/19.0.0.0/grid"),
            _section("grid_owner", "oracle"),
            _section("srvctl_database_list_returncode", "0"),
            _section("srvctl_database_list_stderr", "DIA-49802 missing permission on ADR home directory"),
            _section("database_list", ""),
            _section("pmon", ""),
            _section("oratab", "+ASM1:/u01/app/19.0.0.0/grid:N"),
        ]
    )
    record = DBInventoryCollector(FakeRunner(stdout)).collect_host("c1", FakeHost(), FakeLogger())
    assert record.status == "partial"
    assert record.collection_status == "partial"
    assert record.collection_error == "srvctl database list empty"
    assert record.srvctl_database_list_stderr == "DIA-49802 missing permission on ADR home directory"
    assert record.db_resource_details_count == 0


def test_pmon_oratab_fallback_collects_local_sql_details() -> None:
    calls: list[tuple[str, str, bool]] = []

    def executor(oracle_home: str, sid: str, sql: str, use_cdb_views: bool) -> CommandResult:
        calls.append((oracle_home, sid, use_cdb_views))
        return _result(stdout="node1|DB1|PRIMARY|READ WRITE|19.0.0.0.0|true|1|1|2|3|4|300|8|10|5\n")

    rows = _collect_pmon_oratab_fallback_details(
        None,
        FakeHost(),
        "c1",
        "node1",
        "10.0.0.1",
        "now",
        ["DB1_1"],
        "DB1:/u01/app/oracle/product/19/dbhome_1:Y\n",
        "node1.example.com",
        sql_executor=executor,
    )
    assert calls == [("/u01/app/oracle/product/19/dbhome_1", "DB1_1", True)]
    assert rows[0]["source"] == "pmon_oratab_fallback"
    assert rows[0]["mapping_source"] == "pmon_oratab_fallback"
    assert rows[0]["collection_status"] == "success"
    assert rows[0]["DB_NAME"] == "DB1"
