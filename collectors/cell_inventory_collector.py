"""Exadata storage-cell inventory via dcli + cellcli.

The compute-node collectors never reach the storage grid, so cell image
versions, models, and flash-cache capacity were invisible. A DMA collects
this from a compute node by fanning out to the cells with ``dcli``:

    dcli -g <cell_group> -l <cell_user> "cellcli -e list cell detail"

``dcli`` prefixes every output line with ``<cellhost>: ``. The ``... detail``
form emits one ``attr: value`` pair per line, which parses unambiguously
even for attributes containing spaces (e.g. ``makeModel``). This collector
runs once per cluster from a representative compute host and merges the
cell, flashcache, and physicaldisk listings into one row per cell.

Execution model matches the rest of the project: a single command streamed
over SSH (``runner.run_command``); no scripts copied to the target. If
``dcli`` or the cell group file is absent the cluster simply yields a
failed record with a clear message, never aborting the run.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import ClusterConfig, HostConfig


CELL_INVENTORY_COLUMNS = [
    "Cluster",
    "source_host",
    "source_address",
    "CELL_NAME",
    "CELL_VERSION",
    "MAKE_MODEL",
    "STATUS",
    "CPU_COUNT",
    "FLASH_CACHE_GB",
    "FLASH_CACHE_MODE",
    "HARD_DISK_GB",
    "FLASH_DISK_GB",
    "Collected_At",
    "collection_status",
    "collection_error",
    "error_category",
]


@dataclass
class CellInventoryRecord:
    Cluster: str
    source_host: str = ""
    source_address: str = ""
    CELL_NAME: str = ""
    CELL_VERSION: str = ""
    MAKE_MODEL: str = ""
    STATUS: str = ""
    CPU_COUNT: str = ""
    FLASH_CACHE_GB: str = ""
    FLASH_CACHE_MODE: str = ""
    HARD_DISK_GB: str = ""
    FLASH_DISK_GB: str = ""
    Collected_At: str = ""
    collection_status: str = "success"
    collection_error: str = ""
    error_category: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return {column: getattr(self, column) for column in CELL_INVENTORY_COLUMNS}

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


DEFAULT_CELL_GROUP = "/opt/oracle.SupportTools/onecommand/cell_group"
DEFAULT_CELL_USER = "celladmin"


def build_dcli_cellcli_command(
    cell_group: str, cell_user: str, cellcli_command: str, timeout_seconds: int = 60
) -> str:
    """Build a ``dcli -g <group> -l <user> "cellcli -e <cmd>"`` invocation."""

    inner = f"cellcli -e {cellcli_command}"
    return " ".join(
        [
            "timeout",
            f"{int(timeout_seconds)}s",
            "dcli",
            "-g",
            shlex.quote(cell_group),
            "-l",
            shlex.quote(cell_user),
            shlex.quote(inner),
        ]
    )


_DETAIL_LINE = re.compile(r"^(?P<cell>\S+?):\s+(?P<attr>[A-Za-z0-9_]+):\s*(?P<value>.*)$")


def parse_dcli_detail(text: str) -> dict[str, dict[str, str]]:
    """Parse ``dcli "... list <obj> detail"`` output into per-cell attr dicts.

    Lines look like ``cel01: cellVersion:    OSS_23.1.0.0.0_...``. Returns
    ``{cell_host: {attr: value, ...}}``. Lines that do not match the
    ``cell: attr: value`` shape (banners, blank lines) are ignored. When a
    cell repeats an attribute (multiple objects, e.g. several flashcache
    entries) the values are summed if numeric-with-unit, else last-wins;
    callers that need per-object rows should use :func:`parse_dcli_rows`.
    """

    result: dict[str, dict[str, str]] = {}
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        match = _DETAIL_LINE.match(raw_line.strip())
        if not match:
            continue
        cell = match.group("cell")
        attr = match.group("attr")
        value = match.group("value").strip()
        result.setdefault(cell, {})[attr] = value
    return result


def parse_dcli_detail_multi(text: str) -> dict[str, list[dict[str, str]]]:
    """Parse detail output where each cell may list multiple objects.

    A new object starts whenever the ``name`` attribute reappears for a
    cell. Returns ``{cell_host: [ {attr: value, ...}, ... ]}``. Used for
    physicaldisk / griddisk listings where capacity must be summed across
    many objects per cell.
    """

    result: dict[str, list[dict[str, str]]] = {}
    current: dict[str, dict[str, str]] = {}
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        match = _DETAIL_LINE.match(raw_line.strip())
        if not match:
            continue
        cell, attr, value = match.group("cell"), match.group("attr"), match.group("value").strip()
        if attr == "name":
            # Start a new object for this cell.
            obj = {"name": value}
            result.setdefault(cell, []).append(obj)
            current[cell] = obj
        else:
            obj = current.get(cell)
            if obj is None:
                obj = {}
                result.setdefault(cell, []).append(obj)
                current[cell] = obj
            obj[attr] = value
    return result


_SIZE_UNITS = {"T": 1024.0, "G": 1.0, "M": 1.0 / 1024.0, "K": 1.0 / 1024.0 / 1024.0}


def parse_cell_size_gb(value: str) -> float | None:
    """Convert a cellcli size string (e.g. ``5.82105T`` / ``745.211G``) to GB."""

    if value is None:
        return None
    text = str(value).strip().rstrip("B").strip()
    if not text:
        return None
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([TGMK])?$", text, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "G").upper()
    return round(number * _SIZE_UNITS.get(unit, 1.0), 2)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# cellcli detail commands issued via dcli. Kept as a mapping so callers can
# inject results per kind in tests.
CELLCLI_COMMANDS = {
    "cell": "list cell detail",
    "flashcache": "list flashcache detail",
    "physicaldisk": "list physicaldisk detail",
}


class CellInventoryCollector:
    """Collect per-cell image/model/capacity from a compute node via dcli."""

    def __init__(
        self, runner: SSHRunner | None, logger: logging.Logger | None = None
    ) -> None:
        self.runner = runner
        self.logger = logger or logging.getLogger(__name__)

    def collect_cluster(
        self,
        cluster: "ClusterConfig",
        host: "HostConfig",
        *,
        enabled: bool = True,
        cell_group: str = DEFAULT_CELL_GROUP,
        cell_user: str = DEFAULT_CELL_USER,
        timeout_seconds: int = 60,
        command_executor=None,
    ) -> list[CellInventoryRecord]:
        if not enabled:
            return []

        now = _utc_now()
        results = {}
        for kind, cellcli_cmd in CELLCLI_COMMANDS.items():
            command = build_dcli_cellcli_command(
                cell_group, cell_user, cellcli_cmd, timeout_seconds
            )
            result = self._execute(host, kind, command, command_executor)
            results[kind] = result

        cell_result = results["cell"]
        if not cell_result.ok:
            return [
                CellInventoryRecord(
                    Cluster=cluster.name,
                    source_host=host.name,
                    source_address=host.address,
                    Collected_At=now,
                    collection_status="failed",
                    collection_error=_cell_error(cell_result),
                    error_category=_cell_error_category(cell_result),
                )
            ]

        cells = parse_dcli_detail(cell_result.stdout)
        flash = (
            parse_dcli_detail_multi(results["flashcache"].stdout)
            if results["flashcache"].ok
            else {}
        )
        disks = (
            parse_dcli_detail_multi(results["physicaldisk"].stdout)
            if results["physicaldisk"].ok
            else {}
        )

        records: list[CellInventoryRecord] = []
        for cell_host, attrs in sorted(cells.items()):
            flash_gb, flash_mode = _flashcache_summary(flash.get(cell_host, []))
            hard_gb, flash_disk_gb = _physicaldisk_summary(disks.get(cell_host, []))
            records.append(
                CellInventoryRecord(
                    Cluster=cluster.name,
                    source_host=host.name,
                    source_address=host.address,
                    CELL_NAME=attrs.get("name", cell_host),
                    CELL_VERSION=attrs.get("cellVersion", ""),
                    MAKE_MODEL=attrs.get("makeModel", ""),
                    STATUS=attrs.get("status", ""),
                    CPU_COUNT=attrs.get("cpuCount", ""),
                    FLASH_CACHE_GB="" if flash_gb is None else f"{flash_gb}",
                    FLASH_CACHE_MODE=flash_mode,
                    HARD_DISK_GB="" if hard_gb is None else f"{hard_gb}",
                    FLASH_DISK_GB="" if flash_disk_gb is None else f"{flash_disk_gb}",
                    Collected_At=now,
                    collection_status="success",
                )
            )
        if not records:
            return [
                CellInventoryRecord(
                    Cluster=cluster.name,
                    source_host=host.name,
                    source_address=host.address,
                    Collected_At=now,
                    collection_status="failed",
                    collection_error="no_cells_parsed",
                    error_category="EMPTY_OUTPUT",
                )
            ]
        return records

    def _execute(self, host, kind, command, command_executor):
        if command_executor is not None:
            return command_executor(kind, command)
        if self.runner is None:
            raise ValueError("runner is required when command_executor is not supplied")
        return self.runner.run_command(host, command)


def _flashcache_summary(objects: list[dict[str, str]]) -> tuple[float | None, str]:
    total = 0.0
    found = False
    mode = ""
    for obj in objects:
        size = parse_cell_size_gb(obj.get("size", ""))
        if size is not None:
            total += size
            found = True
        if not mode:
            mode = obj.get("flashCacheMode") or obj.get("status") or ""
    return (round(total, 2) if found else None), mode


def _physicaldisk_summary(objects: list[dict[str, str]]) -> tuple[float | None, float | None]:
    hard = 0.0
    flash = 0.0
    hard_found = flash_found = False
    for obj in objects:
        size = parse_cell_size_gb(obj.get("physicalSize", "") or obj.get("size", ""))
        if size is None:
            continue
        disk_type = (obj.get("diskType") or "").lower()
        if "flash" in disk_type:
            flash += size
            flash_found = True
        else:
            hard += size
            hard_found = True
    return (
        round(hard, 2) if hard_found else None,
        round(flash, 2) if flash_found else None,
    )


def _cell_error(result) -> str:
    if getattr(result, "timed_out", False):
        return "dcli/cellcli timed out"
    stderr = (getattr(result, "stderr", "") or "").strip()
    stdout = (getattr(result, "stdout", "") or "").strip()
    detail = stderr or stdout or f"dcli exited with {getattr(result, 'returncode', '')}"
    return detail


def _cell_error_category(result) -> str:
    if getattr(result, "timed_out", False):
        return "TIMEOUT"
    combined = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}".lower()
    if "command not found" in combined or "no such file" in combined or "dcli" in combined and "not" in combined:
        return "DCLI_NOT_FOUND"
    if "permission denied" in combined or "publickey" in combined:
        return "CELL_AUTH"
    return "UNKNOWN"
