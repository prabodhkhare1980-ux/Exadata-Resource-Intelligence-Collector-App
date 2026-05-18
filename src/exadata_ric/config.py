"""Configuration loading and normalization for cluster collection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the collector configuration is invalid."""


@dataclass(frozen=True)
class AuthConfig:
    """Authentication settings for a resolved target host."""

    method: str = "password"
    key_file: str | None = None
    sudo: bool = True
    sudo_password: str = "same_as_ssh"


@dataclass(frozen=True)
class HostConfig:
    """One host to collect from."""

    name: str
    address: str
    cluster: str
    environment: str
    ssh_user: str
    auth: AuthConfig
    port: int = 22
    timeout_seconds: int = 60
    strict_host_key_checking: str = "accept-new"


@dataclass(frozen=True)
class CollectionConfig:
    """Top-level collection settings."""

    output_dir: Path
    hosts: tuple[HostConfig, ...]


def load_config(path: str | Path) -> CollectionConfig:
    """Load and validate a cluster configuration file."""

    config_path = Path(path)
    raw = _load_mapping(config_path)

    environments = raw.get("environments", {})
    clusters = raw.get("clusters", [])
    collection = raw.get("collection", {})
    ssh_defaults = collection.get("ssh", {})

    if not isinstance(environments, dict):
        raise ConfigError("'environments' must be a mapping")
    if not isinstance(clusters, list):
        raise ConfigError("'clusters' must be a list")

    hosts: list[HostConfig] = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            raise ConfigError("each cluster must be a mapping")
        cluster_name = _required_str(cluster, "name", "cluster")
        environment_name = _required_str(cluster, "environment", cluster_name)
        environment = environments.get(environment_name, {})
        if not isinstance(environment, dict):
            raise ConfigError(f"environment '{environment_name}' must be a mapping")

        cluster_auth = _merge_auth(environment.get("auth"), cluster.get("auth"))
        cluster_user = _first_str(cluster.get("ssh_user"), environment.get("ssh_user"))
        if not cluster_user:
            raise ConfigError(
                f"cluster '{cluster_name}' must resolve an ssh_user from the cluster or environment"
            )

        for host in cluster.get("hosts", []):
            if not isinstance(host, dict):
                raise ConfigError(f"cluster '{cluster_name}' hosts must be mappings")
            host_name = _required_str(host, "name", f"cluster '{cluster_name}' host")
            address = _first_str(host.get("address"), host.get("hostname"), host_name)
            host_user = _first_str(host.get("ssh_user"), cluster_user)
            host_auth = _merge_auth(cluster_auth.__dict__, host.get("auth"))
            hosts.append(
                HostConfig(
                    name=host_name,
                    address=address,
                    cluster=cluster_name,
                    environment=environment_name,
                    ssh_user=host_user,
                    auth=host_auth,
                    port=int(host.get("port", ssh_defaults.get("port", 22))),
                    timeout_seconds=int(
                        host.get("timeout_seconds", ssh_defaults.get("timeout_seconds", 60))
                    ),
                    strict_host_key_checking=str(
                        host.get(
                            "strict_host_key_checking",
                            ssh_defaults.get("strict_host_key_checking", "accept-new"),
                        )
                    ),
                )
            )

    if not hosts:
        raise ConfigError("configuration must define at least one host")

    output_dir = Path(collection.get("output_dir", "output"))
    return CollectionConfig(output_dir=output_dir, hosts=tuple(hosts))


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            data = _load_simple_yaml(text)
        else:
            data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError("configuration root must be a mapping")
    return data


def _merge_auth(base: Any, override: Any) -> AuthConfig:
    merged: dict[str, Any] = {}
    if isinstance(base, AuthConfig):
        merged.update(base.__dict__)
    elif isinstance(base, dict):
        merged.update(base)
    elif base is not None:
        raise ConfigError("auth blocks must be mappings")

    if isinstance(override, dict):
        merged.update(override)
    elif override is not None:
        raise ConfigError("auth blocks must be mappings")

    method = str(merged.get("method", "password")).lower()
    if method not in {"password", "key"}:
        raise ConfigError("auth.method must be 'password' or 'key'")
    return AuthConfig(
        method=method,
        key_file=_first_str(merged.get("key_file")),
        sudo=bool(merged.get("sudo", True)),
        sudo_password=str(merged.get("sudo_password", "same_as_ssh")),
    )


def _required_str(mapping: dict[str, Any], key: str, label: str) -> str:
    value = _first_str(mapping.get(key))
    if not value:
        raise ConfigError(f"{label} requires '{key}'")
    return value


def _first_str(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None



def _load_simple_yaml(text: str) -> Any:
    """Parse the small YAML subset used by the sample config.

    This fallback keeps Phase 1 installable with the standard library while still
    accepting conventional indentation-based mappings and lists. Operators who
    need full YAML features can install the optional PyYAML extra.
    """

    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        without_comment = raw.split("#", 1)[0].rstrip()
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        lines.append((indent, without_comment.strip()))
    if not lines:
        return {}
    data, index = _parse_yaml_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ConfigError("unsupported YAML structure")
    return data


def _parse_yaml_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if lines[index][1].startswith("- "):
        return _parse_yaml_list(lines, index, indent)
    return _parse_yaml_mapping(lines, index, indent)


def _parse_yaml_mapping(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ConfigError(f"unexpected indentation near '{content}'")
        if content.startswith("- "):
            break
        key, value = _split_yaml_key_value(content)
        index += 1
        if value is None:
            if index < len(lines) and lines[index][0] > current_indent:
                child, index = _parse_yaml_block(lines, index, lines[index][0])
                mapping[key] = child
            else:
                mapping[key] = None
        else:
            mapping[key] = _parse_yaml_scalar(value)
    return mapping, index


def _parse_yaml_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    values: list[Any] = []
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ConfigError(f"unexpected indentation near '{content}'")
        if not content.startswith("- "):
            break
        item = content[2:].strip()
        index += 1
        if not item:
            if index < len(lines) and lines[index][0] > current_indent:
                child, index = _parse_yaml_block(lines, index, lines[index][0])
                values.append(child)
            else:
                values.append(None)
            continue
        if ":" in item:
            key, value = _split_yaml_key_value(item)
            item_mapping: dict[str, Any] = {key: None if value is None else _parse_yaml_scalar(value)}
            if index < len(lines) and lines[index][0] > current_indent:
                child, index = _parse_yaml_mapping(lines, index, lines[index][0])
                item_mapping.update(child)
            values.append(item_mapping)
        else:
            values.append(_parse_yaml_scalar(item))
    return values, index


def _split_yaml_key_value(content: str) -> tuple[str, str | None]:
    if ":" not in content:
        raise ConfigError(f"expected key/value pair near '{content}'")
    key, value = content.split(":", 1)
    key = key.strip().strip('"\'')
    value = value.strip()
    return key, value if value else None


def _parse_yaml_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value
