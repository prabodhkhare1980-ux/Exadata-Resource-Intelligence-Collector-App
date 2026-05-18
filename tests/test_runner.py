from exadata_ric.config import AuthConfig, HostConfig
from exadata_ric.runner import build_phase1_script, parse_sections
from exadata_ric.collectors import PHASE1_COLLECTORS


def _host():
    return HostConfig(
        name="db01",
        address="db01.example.com",
        cluster="rac01",
        environment="onprem",
        ssh_user="user1",
        auth=AuthConfig(method="password"),
    )


def test_build_script_contains_all_phase1_sections():
    script = build_phase1_script(PHASE1_COLLECTORS)

    assert "SECTION\tos" in script
    assert "SECTION\tcpu_memory" in script
    assert "SECTION\tfilesystem" in script


def test_parse_sections_and_collectors():
    sections = parse_sections(
        "SECTION\tos\n"
        "hostname\tdb01\n"
        "END\tos\n"
        "SECTION\tcpu_memory\n"
        "cpu_count\t8\n"
        "load_1m\t0.5\n"
        "END\tcpu_memory\n"
        "SECTION\tfilesystem\n"
        "/dev/sda1\txfs\t100\t40\t60\t40%\t/u01\n"
        "END\tfilesystem\n"
    )

    host = _host()
    parsed = {collector.name: collector.parse(host, sections) for collector in PHASE1_COLLECTORS}
    assert parsed["os"].rows[0]["hostname"] == "db01"
    assert parsed["cpu_memory"].rows[0]["cpu_count"] == 8
    assert parsed["filesystem"].rows[0]["mountpoint"] == "/u01"
