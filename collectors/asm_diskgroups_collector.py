"""ASM diskgroup collector."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from collectors.shared_context import SharedHostContext
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig

SECTION_PREFIX = "__ERIC_SECTION__:"


@dataclass
class ASMDiskgroupRecord:
    cluster: str
    host: str
    address: str
    diskgroup_name: str = ""
    state: str = ""
    type: str = ""
    total_mb: int = 0
    free_mb: int = 0
    usable_file_mb: int = 0
    used_pct: float = 0.0
    warning_level: str = ""
    asm_collection_status: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return asdict(self)

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


class ASMDiskgroupCollector:
    def __init__(self, runner: SSHRunner, context: SharedHostContext | None = None, logger: logging.Logger | None = None) -> None:
        self.runner = runner
        self.context = context
        self.logger = logger or logging.getLogger(__name__)

    def collect_host(self, cluster_name: str, host: "HostConfig", logger: logging.Logger, *, enabled: bool = True, timeout_seconds: int = 30) -> list[ASMDiskgroupRecord]:
        logger.info("Starting ASM diskgroup collection for %s", host.name)
        if not enabled:
            logger.warning("ASM collection skipped/failed for %s", host.name)
            return [ASMDiskgroupRecord(cluster=cluster_name, host=host.name, address=host.address, asm_collection_status="skipped")]

        script = ASM_COLLECTION_SCRIPT.replace("__ASM_TIMEOUT_SECONDS__", str(max(1, int(timeout_seconds))))
        result = self.runner.run_script(host, script)
        if not result.ok:
            logger.warning("ASM collection skipped/failed for %s: %s", host.name, result.error or result.stderr.strip() or f"SSH exited with {result.returncode}")
            return [ASMDiskgroupRecord(cluster=cluster_name, host=host.name, address=host.address, asm_collection_status="failed", warning_level="ERROR")]

        sections = _parse_sections(result.stdout)
        status = sections.get("asm_collection_status", "failed").strip() or "failed"
        rows = _parse_lsdg(cluster_name, host.name, host.address, sections.get("asm_lsdg", ""), status)
        if status == "success":
            logger.info("Completed ASM diskgroup collection for %s", host.name)
        else:
            error_detail = sections.get("asm_error", "").strip()
            if error_detail:
                logger.warning("ASM collection skipped/failed for %s: %s", host.name, error_detail.splitlines()[0])
            else:
                logger.warning("ASM collection skipped/failed for %s", host.name)
        return rows


def _parse_sections(output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in output.splitlines():
        if line.startswith(SECTION_PREFIX):
            current = line.removeprefix(SECTION_PREFIX).strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _parse_lsdg(cluster: str, host: str, address: str, text: str, status: str) -> list[ASMDiskgroupRecord]:
    rows: list[ASMDiskgroupRecord] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("state") or set(stripped) <= {"-", " "}:
            continue
        parts = stripped.split()
        if len(parts) < 13:
            continue
        total_mb = _to_int(parts[6])
        free_mb = _to_int(parts[7])
        usable_file_mb = _to_int(parts[9])
        used_pct = round(((total_mb - free_mb) / total_mb) * 100, 2) if total_mb > 0 else 0.0
        warning_level = "OK"
        if used_pct >= 95:
            warning_level = "CRITICAL"
        elif used_pct >= 85:
            warning_level = "WARNING"
        rows.append(ASMDiskgroupRecord(cluster=cluster, host=host, address=address, diskgroup_name=parts[12].rstrip('/'), state=parts[0], type=parts[1], total_mb=total_mb, free_mb=free_mb, usable_file_mb=usable_file_mb, used_pct=used_pct, warning_level=warning_level, asm_collection_status=status))
    rows.append(ASMDiskgroupRecord(cluster=cluster, host=host, address=address, asm_collection_status=status))
    return rows


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


ASM_COLLECTION_SCRIPT = r'''
set -o pipefail
emit_section() {
  printf '\n__ERIC_SECTION__:%s\n' "$1"
}

grid_home="$(awk -F: '/^\+ASM/ {print $2; exit}' /etc/oratab 2>/dev/null)"
if [ -z "$grid_home" ]; then
  emit_section asm_collection_status
  echo skipped
  exit 0
fi

asm_runner=''
if [ "$(id -un 2>/dev/null || true)" = "root" ]; then
  asm_runner='su -s /bin/bash -c'
elif [ "$(id -un 2>/dev/null || true)" = "grid" ]; then
  asm_runner='bash -c'
else
  asm_runner='sudo -n -u grid bash -c'
fi

emit_section asm_lsdg
asm_output="$($asm_runner "export ORACLE_HOME='$grid_home'; export PATH=\$ORACLE_HOME/bin:\$PATH; timeout __ASM_TIMEOUT_SECONDS__s asmcmd lsdg" 2>&1)"
asm_rc=$?
printf '%s
' "$asm_output"

emit_section asm_collection_status
if [ $asm_rc -eq 0 ]; then
  echo success
else
  echo failed
  emit_section asm_error
  printf '%s
' "$asm_output"
fi
'''.lstrip()
