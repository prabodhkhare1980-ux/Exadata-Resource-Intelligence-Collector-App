from pathlib import Path

from exadata_ric.config import load_config


def test_load_sample_config_resolves_users():
    config = load_config(Path("config/clusters.yaml"))

    by_name = {host.name: host for host in config.hosts}
    assert by_name["onprem-rac01-db01"].ssh_user == "your_onprem_personal_id"
    assert by_name["oci-vmcluster01-db01"].ssh_user == "cluster_specific_oci_id"
    assert by_name["oci-vmcluster01-db02"].ssh_user == "host_specific_override_id"
    assert by_name["onprem-rac01-db01"].auth.method == "password"
