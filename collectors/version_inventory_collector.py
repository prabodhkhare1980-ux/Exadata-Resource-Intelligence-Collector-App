"""GI and Exadata image version inventory collector."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from collectors.shared_context import SharedHostContext
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig

SECTION_PREFIX = "__ERIC_VERSION_SECTION__:"


@dataclass
class VersionInventoryRecord:
    cluster: str
    host: str
    address: str
    collected_at: str
    collection_status: str = "failed"
    collection_error: str = ""
    ssh_returncode: int | None = None
    image_version: str = ""
    exadata_software_version: str = ""
    image_activated: str = ""
    image_status: str = ""
    gi_active_version: str = ""
    gi_software_patch_level: str = ""
    gi_release_version: str = ""
    gi_release_patch_level: str = ""
    gi_release_patch_string: str = ""
    gi_release_patch_list: list[str] = field(default_factory=list)
    imageinfo: dict[str, str] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)

    def to_csv_row(self) -> dict[str, object]:
        return {
            "cluster": self.cluster,
            "host": self.host,
            "address": self.address,
            "collected_at": self.collected_at,
            "collection_status": self.collection_status,
            "collection_error": self.collection_error,
            "ssh_returncode": "" if self.ssh_returncode is None else str(self.ssh_returncode),
            "image_version": self.image_version,
            "exadata_software_version": self.exadata_software_version,
            "image_activated": self.image_activated,
            "image_status": self.image_status,
            "gi_active_version": self.gi_active_version,
            "gi_software_patch_level": self.gi_software_patch_level,
            "gi_release_version": self.gi_release_version,
            "gi_release_patch_level": self.gi_release_patch_level,
            "gi_release_patch_string": self.gi_release_patch_string,
            "gi_release_patch_list": json.dumps(self.gi_release_patch_list),
            "imageinfo_json": json.dumps(self.imageinfo, sort_keys=True),
        }

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


class VersionInventoryCollector:
    def __init__(self, runner: SSHRunner, context: SharedHostContext | None = None, logger: logging.Logger | None = None) -> None:
        self.runner = runner
        self.context = context
        self.logger = logger or logging.getLogger(__name__)

    def collect_host(self, cluster_name: str, host: "HostConfig", logger: logging.Logger) -> VersionInventoryRecord:
        logger.info("Starting version inventory collection for %s", host.name)
        collected_at = _utc_now()
        result = self._run_host_script(host)
        if not result.ok:
            error = result.error or result.stderr.strip() or f"Version inventory command exited with {result.returncode}"
            logger.warning("Version inventory collection failed for %s: %s", host.name, error)
            return VersionInventoryRecord(
                cluster=cluster_name,
                host=host.name,
                address=host.address,
                collected_at=collected_at,
                collection_status="failed",
                collection_error=error,
                ssh_returncode=result.returncode,
                raw={"stdout": result.stdout, "stderr": result.stderr},
            )

        sections = _parse_sections(result.stdout)
        record = parse_version_inventory_sections(
            cluster_name,
            host.name,
            host.address,
            collected_at,
            sections,
            ssh_returncode=result.returncode,
        )
        logger.info("Completed version inventory collection for %s", host.name)
        return record

    def _run_host_script(self, host: "HostConfig"):
        # Stream this script over the existing SSH runner. It only executes commands remotely;
        # it does not copy scripts or create remote temp files.
        return self.runner.run_script(host, VERSION_INVENTORY_SCRIPT)


VERSION_INVENTORY_SCRIPT = r'''
emit_section() {
  printf '\n__ERIC_VERSION_SECTION__:%s\n' "$1"
}

setup_grid_env() {
  grid_home="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null || true)"
  if [ -n "$grid_home" ]; then
    export ORACLE_HOME="$grid_home"
    export PATH="$ORACLE_HOME/bin:$PATH"
  fi
}

setup_grid_env

emit_section imageinfo
(imageinfo 2>&1 || true)

emit_section gi_active_version
(crsctl query crs activeversion 2>&1 || true)

emit_section gi_software_patch
(crsctl query crs softwarepatch 2>&1 || true)

emit_section gi_release_version
(crsctl query crs releaseversion 2>&1 || true)

emit_section gi_release_patch
(crsctl query crs releasepatch 2>&1 || true)
'''.lstrip()


def parse_version_inventory_sections(
    cluster: str,
    host: str,
    address: str,
    collected_at: str,
    sections: dict[str, str],
    *,
    ssh_returncode: int | None = None,
) -> VersionInventoryRecord:
    imageinfo = parse_imageinfo(sections.get("imageinfo", ""))
    release_patch = parse_release_patch(sections.get("gi_release_patch", ""))
    return VersionInventoryRecord(
        cluster=cluster,
        host=host,
        address=address,
        collected_at=collected_at,
        collection_status="success",
        ssh_returncode=ssh_returncode,
        image_version=imageinfo.get("image_version", ""),
        exadata_software_version=imageinfo.get("exadata_software_version", ""),
        image_activated=imageinfo.get("image_activated", ""),
        image_status=imageinfo.get("image_status", ""),
        gi_active_version=_first_bracket_value(sections.get("gi_active_version", "")),
        gi_software_patch_level=_first_bracket_value(sections.get("gi_software_patch", "")),
        gi_release_version=_first_bracket_value(sections.get("gi_release_version", "")),
        gi_release_patch_level=release_patch["level"],
        gi_release_patch_string=release_patch["patch_string"],
        gi_release_patch_list=release_patch["patch_list"],
        imageinfo=imageinfo,
        raw=sections,
    )


def parse_imageinfo(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized_key = _normalize_key(key)
        if normalized_key:
            values[normalized_key] = value.strip()
    return values


def parse_release_patch(output: str) -> dict[str, object]:
    bracket_values = _bracket_values(output)
    level = ""
    patch_list: list[str] = []
    patch_string = ""

    level_match = re.search(r"patch level is\s*\[([^\]]*)\]", output, flags=re.IGNORECASE)
    if level_match:
        level = level_match.group(1).strip()
    elif bracket_values:
        level = bracket_values[0]

    list_match = re.search(r"list of patches\s*\[([^\]]*)\]", output, flags=re.IGNORECASE)
    if list_match:
        patch_list = [item for item in list_match.group(1).split() if item]
    elif len(bracket_values) >= 2:
        patch_list = [item for item in bracket_values[1].split() if item]

    string_match = re.search(r"patch string is\s*\[([^\]]*)\]", output, flags=re.IGNORECASE)
    if string_match:
        patch_string = string_match.group(1).strip()
    elif len(bracket_values) >= 3:
        patch_string = bracket_values[2]

    return {"level": level, "patch_list": patch_list, "patch_string": patch_string}


def _parse_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in output.splitlines():
        if line.startswith(SECTION_PREFIX):
            current = line.removeprefix(SECTION_PREFIX).strip()
            sections[current] = []
            continue
        if current is not None:
            if _is_prompt_line(line):
                continue
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _first_bracket_value(output: str) -> str:
    values = _bracket_values(output)
    return values[0] if values else ""


def _bracket_values(output: str) -> list[str]:
    return [value.strip() for value in re.findall(r"\[([^\]]*)\]", output or "")]


def _normalize_key(key: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    return normalized


def _is_prompt_line(line: str) -> bool:
    stripped = line.strip()
    if stripped in {"$", "#", ">"}:
        return True
    return stripped.startswith("bash-") and stripped.endswith("#")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
