from exadata_ric.collectors.grid_env_detector import GridEnvDetectorCollector
from exadata_ric.config import AuthConfig, HostConfig, PrivilegeConfig


def _host() -> HostConfig:
    return HostConfig(
        name="db01",
        address="db01.example.com",
        cluster="rac01",
        environment="onprem",
        ssh_user="srcordma",
        auth=AuthConfig(method="ssh_key", key_file=".secrets/ssh/srcordma_id_rsa"),
        privilege=PrivilegeConfig(),
    )


def test_parse_ignores_invalid_srvctl_database_names() -> None:
    collector = GridEnvDetectorCollector()
    sections = {
        "srvctl_databases": [
            ["db_unique_name", "ORCL1"],
            ["db_unique_name", '/,"",$0);'],
            ["db_unique_name", "ora.scan1.vip"],
        ],
        "srvctl_details": [
            ["db_unique_name", "ORCL1"],
            ["config_raw", "Database unique name: ORCL1"],
            ["status_raw", "Instance ORCL1_1 is running on node node1"],
            ["db_unique_name", '/,"",$0);'],
            ["config_raw", "PRKF-1125 : multiple values specified"],
            ["status_raw", "PRKF-1125 : multiple values specified"],
        ],
        "pmon_raw": [],
    }

    result = collector.parse(_host(), sections)

    databases = result.rows[0]["oracle_inventory"]["srvctl_databases"]
    assert len(databases) == 1
    assert databases[0]["db_unique_name"] == "ORCL1"
