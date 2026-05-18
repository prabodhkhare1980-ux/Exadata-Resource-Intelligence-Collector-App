"""Inventory loading and validation for Exadata Resource Intelligence Collector."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class HostConfig:
    """Connection settings for a single remote host."""

    name: str
    address: str
    user: str | None = None
    environment: str = ""
    auth_method: str = "password"
    strict_host_key_checking: str = "accept-new"
    port: int = 22
    sudo: bool = True
    timeout_seconds: int = 60
    ssh_options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClusterConfig:
    """A group of hosts that belong to one Exadata/RAC cluster."""

    name: str
    environment: str
    hosts: list[HostConfig]


@dataclass(frozen=True)
class Inventory:
    """Validated inventory file contents."""

    clusters: list[ClusterConfig]
    output_dir: Path = Path("output")
    logs_dir: Path = Path("logs")


def load_inventory(path: str | Path) -> Inventory:
    """Load and validate a YAML inventory file.

    Args:
        path: Path to a YAML file that contains defaults and cluster host entries.

    Returns:
        A validated Inventory instance.

    Raises:
        ValueError: If the YAML structure is invalid or required values are absent.
    """

    inventory_path = Path(path)
    with inventory_path.open("r", encoding="utf-8") as inventory_file:
        data = yaml.safe_load(inventory_file) or {}

    if not isinstance(data, dict):
        raise ValueError("Inventory root must be a YAML mapping.")

    defaults = data.get("defaults", {}) or {}
    if not isinstance(defaults, dict):
        raise ValueError("Inventory 'defaults' must be a mapping when provided.")
    environments = data.get("environments", {}) or {}
    if not isinstance(environments, dict):
        raise ValueError("Inventory 'environments' must be a mapping when provided.")
    collection = data.get("collection", {}) or {}
    if not isinstance(collection, dict):
        raise ValueError("Inventory 'collection' must be a mapping when provided.")

    clusters_data = data.get("clusters")
    if not isinstance(clusters_data, list) or not clusters_data:
        raise ValueError("Inventory must contain a non-empty 'clusters' list.")

    clusters = [
        _parse_cluster(cluster_data, defaults, environments, collection)
        for cluster_data in clusters_data
    ]
    output_dir = Path(
        collection.get("output_dir") or data.get("output_dir") or defaults.get("output_dir") or "output"
    )
    logs_dir = Path(data.get("logs_dir") or defaults.get("logs_dir") or "logs")

    return Inventory(clusters=clusters, output_dir=output_dir, logs_dir=logs_dir)


def _parse_cluster(
    cluster_data: Any,
    defaults: dict[str, Any],
    environments: dict[str, Any],
    collection: dict[str, Any],
) -> ClusterConfig:
    if not isinstance(cluster_data, dict):
        raise ValueError("Each cluster entry must be a mapping.")

    cluster_name = _required_string(cluster_data, "name", "cluster")
    environment = _required_string(cluster_data, "environment", f"cluster '{cluster_name}'")
    environment_data = environments.get(environment) or {}
    if not isinstance(environment_data, dict):
        raise ValueError(f"Environment '{environment}' must be a mapping.")
    hosts_data = cluster_data.get("hosts")
    if not isinstance(hosts_data, list) or not hosts_data:
        raise ValueError(f"Cluster '{cluster_name}' must contain a non-empty hosts list.")

    hosts = [
        _parse_host(host_data, defaults, cluster_data, environment, environment_data, collection, cluster_name)
        for host_data in hosts_data
    ]
    return ClusterConfig(name=cluster_name, environment=environment, hosts=hosts)


def _parse_host(
    host_data: Any,
    defaults: dict[str, Any],
    cluster_data: dict[str, Any],
    environment: str,
    environment_data: dict[str, Any],
    collection: dict[str, Any],
    cluster_name: str,
) -> HostConfig:
    if not isinstance(host_data, dict):
        raise ValueError(f"Each host in cluster '{cluster_name}' must be a mapping.")

    name = _required_string(host_data, "name", f"host in cluster '{cluster_name}'")
    address = str(host_data.get("address") or name)
    user = host_data.get("ssh_user")
    if not user:
        user = cluster_data.get("ssh_user")
    if not user:
        user = environment_data.get("ssh_user")
    port = int(host_data.get("port", collection.get("ssh", {}).get("port", defaults.get("port", 22))))
    sudo = bool(host_data.get("sudo", defaults.get("sudo", True)))
    timeout_seconds = int(
        host_data.get("timeout_seconds", defaults.get("timeout_seconds", 60))
    )
    strict_host_key_checking = str(
        collection.get("ssh", {}).get("strict_host_key_checking", "accept-new")
    )
    auth_method = str((environment_data.get("auth") or {}).get("method", "password"))
    ssh_options = _merge_ssh_options(defaults.get("ssh_options"), host_data.get("ssh_options"))

    if timeout_seconds <= 0:
        raise ValueError(f"Host '{name}' timeout_seconds must be greater than zero.")
    if port <= 0 or port > 65535:
        raise ValueError(f"Host '{name}' port must be between 1 and 65535.")

    return HostConfig(
        name=name,
        address=address,
        user=str(user) if user else None,
        environment=environment,
        auth_method=auth_method,
        strict_host_key_checking=strict_host_key_checking,
        port=port,
        sudo=sudo,
        timeout_seconds=timeout_seconds,
        ssh_options=ssh_options,
    )


def _merge_ssh_options(default_options: Any, host_options: Any) -> list[str]:
    options: list[str] = []
    for option_group in (default_options, host_options):
        if option_group is None:
            continue
        if not isinstance(option_group, list):
            raise ValueError("ssh_options must be a list of ssh option strings.")
        options.extend(str(option) for option in option_group)
    return options


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"Missing required '{key}' for {context}.")
    return str(value).strip()
