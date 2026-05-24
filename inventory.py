"""Inventory loading and validation for Exadata Resource Intelligence Collector."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class HostConfig:
    name: str
    address: str
    user: str
    environment: str
    auth_method: str
    private_key: str | None
    strict_host_key_checking: str
    port: int
    privilege_enabled: bool
    privilege_method: str
    sudo_password_mode: str
    force_tty: bool
    timeout_seconds: int


@dataclass(frozen=True)
class ClusterConfig:
    name: str
    environment: str
    hosts: list[HostConfig]


@dataclass(frozen=True)
class Inventory:
    clusters: list[ClusterConfig]
    output_dir: Path = Path("output")
    logs_dir: Path = Path("logs")
    parallel_enabled: bool = True
    max_clusters: int = 3
    max_hosts_per_cluster: int = 2
    asm_enabled: bool = True
    asm_timeout_seconds: int = 30
    asm_fail_host_on_error: bool = False


def load_inventory(path: str | Path) -> Inventory:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Inventory root must be a YAML mapping.")

    environments = data.get("environments") or {}
    collection = data.get("collection") or {}
    ssh_defaults = collection.get("ssh") or {}
    if not isinstance(environments, dict):
        raise ValueError("'environments' must be a mapping.")

    clusters_data = data.get("clusters")
    if not isinstance(clusters_data, list) or not clusters_data:
        raise ValueError("Inventory must contain a non-empty 'clusters' list.")

    clusters: list[ClusterConfig] = []
    for cluster_data in clusters_data:
        if not isinstance(cluster_data, dict):
            raise ValueError("Each cluster entry must be a mapping.")
        cluster_name = _required_string(cluster_data, "name", "cluster")
        environment = _required_string(cluster_data, "environment", f"cluster '{cluster_name}'")
        env_data = environments.get(environment)
        if not isinstance(env_data, dict):
            raise ValueError(f"Environment '{environment}' must be a mapping.")

        hosts_data = cluster_data.get("hosts")
        if not isinstance(hosts_data, list) or not hosts_data:
            raise ValueError(f"Cluster '{cluster_name}' must contain a non-empty hosts list.")

        hosts: list[HostConfig] = []
        for host_data in hosts_data:
            if not isinstance(host_data, dict):
                raise ValueError(f"Each host in cluster '{cluster_name}' must be a mapping.")
            name = _required_string(host_data, "name", f"host in cluster '{cluster_name}'")
            address = _required_string(host_data, "address", f"host '{name}'")

            user = str(host_data.get("ssh_user") or cluster_data.get("ssh_user") or env_data.get("ssh_user") or "").strip()
            if not user:
                raise ValueError(f"Host '{name}' in cluster '{cluster_name}' could not resolve ssh_user.")

            auth_data = _merge_mapping(env_data.get("auth"), cluster_data.get("auth"), host_data.get("auth"))
            privilege_data = _merge_mapping(env_data.get("privilege"), cluster_data.get("privilege"), host_data.get("privilege"))

            auth_method = str(auth_data.get("method", "password")).strip().lower()
            private_key = _maybe_string(auth_data.get("private_key"))
            if auth_method == "ssh_key" and not private_key:
                raise ValueError(f"Host '{name}' requires auth.private_key when auth.method=ssh_key.")

            hosts.append(
                HostConfig(
                    name=name,
                    address=address,
                    user=user,
                    environment=environment,
                    auth_method=auth_method,
                    private_key=private_key,
                    strict_host_key_checking=str(ssh_defaults.get("strict_host_key_checking", "accept-new")),
                    port=int(host_data.get("port", ssh_defaults.get("port", 22))),
                    privilege_enabled=bool(privilege_data.get("enabled", True)),
                    privilege_method=str(privilege_data.get("method", "sudo")),
                    sudo_password_mode=str(privilege_data.get("sudo_password", "same_as_ssh")),
                    force_tty=bool(privilege_data.get("force_tty", False)),
                    timeout_seconds=int(host_data.get("timeout_seconds", ssh_defaults.get("timeout_seconds", 60))),
                )
            )
        clusters.append(ClusterConfig(name=cluster_name, environment=environment, hosts=hosts))

    output_dir = Path(collection.get("output_dir", "output"))
    parallel_cfg = collection.get("parallel") or {}
    if not isinstance(parallel_cfg, dict):
        raise ValueError("'collection.parallel' must be a mapping.")
    parallel_enabled = bool(parallel_cfg.get("enabled", True))
    max_clusters = int(parallel_cfg.get("max_clusters", 3))
    max_hosts_per_cluster = int(parallel_cfg.get("max_hosts_per_cluster", 2))
    if max_clusters < 1:
        raise ValueError("'collection.parallel.max_clusters' must be >= 1.")
    if max_hosts_per_cluster < 1:
        raise ValueError("'collection.parallel.max_hosts_per_cluster' must be >= 1.")
    asm_cfg = collection.get("asm") or {}
    if not isinstance(asm_cfg, dict):
        raise ValueError("'collection.asm' must be a mapping.")
    return Inventory(
        clusters=clusters,
        output_dir=output_dir,
        logs_dir=Path("logs"),
        parallel_enabled=parallel_enabled,
        max_clusters=max_clusters,
        max_hosts_per_cluster=max_hosts_per_cluster,
        asm_enabled=bool(asm_cfg.get("enabled", True)),
        asm_timeout_seconds=int(asm_cfg.get("timeout_seconds", 30)),
        asm_fail_host_on_error=bool(asm_cfg.get("fail_host_on_error", False)),
    )


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"Missing required '{key}' for {context}.")
    return str(value).strip()


def _maybe_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _merge_mapping(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ValueError("auth/privilege entries must be mappings.")
        merged.update(value)
    return merged
