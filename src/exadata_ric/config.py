"""Configuration loading and normalization for cluster collection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
class PrivilegeConfig:
    enabled: bool = True
    method: str = "sudo"
    sudo_password: str = "none"
    force_tty: bool = False


@dataclass(frozen=True)
class HostConfig:
    """One host to collect from."""

    name: str
    address: str
    cluster: str
    environment: str
    ssh_user: str
    auth: AuthConfig
    privilege: PrivilegeConfig = field(default_factory=PrivilegeConfig)
    port: int = 22
    timeout_seconds: int = 60
    strict_host_key_checking: str = "accept-new"


@dataclass(frozen=True)
class CollectionConfig:
    """Top-level collection settings."""

    output_dir: Path
    hosts: tuple[HostConfig, ...]
    oracle_inventory_allow_pmon_sid_fallback: bool = False
    asm_enabled: bool = True
    asm_timeout_seconds: int = 30
    asm_fail_host_on_error: bool = False
    asm_include_debug: bool = False
    hugepages_enabled: bool = True
    hugepages_timeout_seconds: int = 15
    debug_enabled: bool = False


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
        environment_name = _first_str(cluster.get("environment"))
        if not environment_name:
            raise ConfigError(f"cluster '{cluster_name}' requires 'environment'")
        if environment_name not in environments:
            raise ConfigError(
                f"cluster '{cluster_name}' references unknown environment '{environment_name}'"
            )
        environment = environments[environment_name]
        if not isinstance(environment, dict):
            raise ConfigError(f"environment '{environment_name}' must be a mapping")

        cluster_auth = _merge_auth(environment.get("auth"), cluster.get("auth"))
        cluster_privilege = _merge_privilege(environment.get("privilege"), cluster.get("privilege"))
        cluster_user = _first_str(cluster.get("ssh_user"))
        environment_user = _first_str(environment.get("ssh_user"))

        cluster_addresses: set[str] = set()
        for host in cluster.get("hosts", []):
            if not isinstance(host, dict):
                raise ConfigError(f"cluster '{cluster_name}' hosts must be mappings")
            host_name = _required_str(host, "name", f"cluster '{cluster_name}' host")
            address = _first_str(host.get("address"), host.get("hostname"))
            if not address:
                raise ConfigError(
                    f"cluster '{cluster_name}' host '{host_name}' requires 'address'"
                )
            if address in cluster_addresses:
                raise ConfigError(
                    f"cluster '{cluster_name}' has duplicate host address '{address}'"
                )
            cluster_addresses.add(address)
            host_user = _first_str(host.get("ssh_user"), cluster_user, environment_user)
            if not host_user:
                raise ConfigError(
                    f"cluster '{cluster_name}' host '{host_name}' could not resolve ssh_user"
                )
            host_auth = _merge_auth(cluster_auth.__dict__, host.get("auth"))
            host_privilege = _merge_privilege(cluster_privilege.__dict__, host.get("privilege"))
            hosts.append(
                HostConfig(
                    name=host_name,
                    address=address,
                    cluster=cluster_name,
                    environment=environment_name,
                    ssh_user=host_user,
                    auth=host_auth,
                    privilege=host_privilege,
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
    asm_collection = collection.get("asm", {}) if isinstance(collection, dict) else {}
    asm_enabled = bool(asm_collection.get("enabled", True)) if isinstance(asm_collection, dict) else True
    asm_timeout_seconds = int(asm_collection.get("timeout_seconds", 30)) if isinstance(asm_collection, dict) else 30
    asm_fail_host_on_error = bool(asm_collection.get("fail_host_on_error", False)) if isinstance(asm_collection, dict) else False
    asm_include_debug = bool(asm_collection.get("include_debug", False)) if isinstance(asm_collection, dict) else False
    hugepages_collection = collection.get("hugepages", {}) if isinstance(collection, dict) else {}
    hugepages_enabled = bool(hugepages_collection.get("enabled", True)) if isinstance(hugepages_collection, dict) else True
    hugepages_timeout_seconds = int(hugepages_collection.get("timeout_seconds", 15)) if isinstance(hugepages_collection, dict) else 15
    debug_collection = collection.get("debug", {}) if isinstance(collection, dict) else {}
    debug_enabled = bool(debug_collection.get("enabled", False)) if isinstance(debug_collection, dict) else False
    oracle_inventory = raw.get("oracle_inventory", {})
    allow_fallback = bool(oracle_inventory.get("allow_pmon_sid_fallback", False)) if isinstance(oracle_inventory, dict) else False
    return CollectionConfig(
        output_dir=output_dir,
        hosts=tuple(hosts),
        oracle_inventory_allow_pmon_sid_fallback=allow_fallback,
        asm_enabled=asm_enabled,
        asm_timeout_seconds=asm_timeout_seconds,
        asm_fail_host_on_error=asm_fail_host_on_error,
        asm_include_debug=asm_include_debug,
        hugepages_enabled=hugepages_enabled,
        hugepages_timeout_seconds=hugepages_timeout_seconds,
        debug_enabled=debug_enabled,
    )


def _merge_privilege(base: Any, override: Any) -> PrivilegeConfig:
    merged: dict[str, Any] = {}
    if isinstance(base, PrivilegeConfig):
        merged.update(base.__dict__)
    elif isinstance(base, dict):
        merged.update(base)
    elif base is not None:
        raise ConfigError("privilege blocks must be mappings")

    if isinstance(override, dict):
        merged.update(override)
    elif override is not None:
        raise ConfigError("privilege blocks must be mappings")

    return PrivilegeConfig(
        enabled=bool(merged.get("enabled", True)),
        method=str(merged.get("method", "sudo")).lower(),
        sudo_password=str(merged.get("sudo_password", "none")),
        force_tty=bool(merged.get("force_tty", False)),
    )


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
    if method == "ssh_key":
        method = "key"
    if method not in {"password", "key"}:
        raise ConfigError("auth.method must be 'password', 'key', or 'ssh_key'")
    return AuthConfig(
        method=method,
        key_file=_first_str(merged.get("key_file"), merged.get("private_key")),
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
