from pathlib import Path

from exadata_ric.collectors import PHASE1_COLLECTORS
from exadata_ric.config import AuthConfig, CollectionConfig, HostConfig, PrivilegeConfig
from exadata_ric.runner import build_phase1_script, parse_sections


def _host():
    return HostConfig(
        name="db01",
        address="db01.example.com",
        cluster="rac01",
        environment="onprem",
        ssh_user="user1",
        auth=AuthConfig(method="password"),
        privilege=PrivilegeConfig(),
    )


def test_build_script_contains_all_phase1_sections():
    script = build_phase1_script(PHASE1_COLLECTORS, CollectionConfig(output_dir=Path("output"), hosts=(_host(),)))

    assert "===BEGIN_SECTION:hostname===" in script
    assert "===BEGIN_SECTION:lscpu===" in script
    assert "===BEGIN_SECTION:df===" in script
    assert "export ASM_TIMEOUT_SECONDS=30" in script


def test_parse_sections_marker_format():
    sections = parse_sections(
        "===BEGIN_SECTION:hostname===\n"
        "hostname\tdb01\n"
        "===END_SECTION:hostname===\n"
    )

    assert "hostname" in sections
    assert sections["hostname"][0] == ["hostname", "db01"]
