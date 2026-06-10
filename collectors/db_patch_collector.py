"""OPatch (``opatch lspatches``) inventory per Oracle home.

The version inventory collector captures the Grid Infrastructure active
version and release patch list, but a DMA also needs the patch level of
every *database* Oracle home to spot homes that drift from the GI/cluster
baseline. This collector runs ``$ORACLE_HOME/OPatch/opatch lspatches`` for
each distinct Oracle home discovered on a host (database homes from the DB
inventory, plus the Grid home) and records one row per installed patch.

Execution mirrors the existing model: ``sudo -n -u <home_owner> env
ORACLE_HOME=<home> timeout <n>s <home>/OPatch/opatch lspatches`` over SSH.
No scripts are copied to the target.
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from collectors.db_inventory_collector import DBInventoryRecord, _resolve_db_owner
from ssh_runner import SSHRunner

if TYPE_CHECKING:
    from inventory import HostConfig


DB_PATCH_COLUMNS = [
    "Cluster",
    "HOST_NAME",
    "ORACLE_HOME",
    "HOME_TYPE",
    "HOME_OWNER",
    "PATCH_ID",
    "PATCH_DESCRIPTION",
    "Collected_At",
    "source_host",
    "source_address",
    "patch_count",
    "collection_status",
    "collection_error",
    "error_category",
]


@dataclass
class DBPatchRecord:
    Cluster: str
    HOST_NAME: str
    ORACLE_HOME: str = ""
    HOME_TYPE: str = ""  # "db" or "grid"
    HOME_OWNER: str = ""
    PATCH_ID: str = ""
    PATCH_DESCRIPTION: str = ""
    Collected_At: str = ""
    source_host: str = ""
    source_address: str = ""
    patch_count: int | str = ""
    collection_status: str = "success"
    collection_error: str = ""
    error_category: str = ""
    returncode: int | str = ""
    stdout: str = ""
    stderr: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return {column: getattr(self, column) for column in DB_PATCH_COLUMNS}

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def build_opatch_lspatches_command(
    oracle_home: str, owner: str, timeout_seconds: int = 60
) -> str:
    """Build the sudo/opatch command string for a single Oracle home."""

    opatch = f"{oracle_home}/OPatch/opatch"
    path = f"{oracle_home}/bin:/usr/bin:/bin"
    return " ".join(
        [
            "sudo",
            "-n",
            "-u",
            shlex.quote(owner),
            "env",
            f"ORACLE_HOME={shlex.quote(oracle_home)}",
            f"PATH={shlex.quote(path)}",
            "timeout",
            f"{int(timeout_seconds)}s",
            shlex.quote(opatch),
            "lspatches",
        ]
    )


_NO_PATCHES_MARKERS = (
    "there are no interim patches installed",
    "no interim patches",
)


def parse_opatch_lspatches_output(text: str) -> list[dict[str, str]]:
    """Parse ``opatch lspatches`` output into patch rows.

    Each installed patch is emitted as ``<patch_id>;<description>``. Lines
    that are not patch entries (the trailing ``OPatch succeeded`` banner,
    blanks, the "no patches" message) are ignored. Returns an empty list
    when the home has no interim patches.
    """

    rows: list[dict[str, str]] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if any(marker in lower for marker in _NO_PATCHES_MARKERS):
            continue
        if lower.startswith("opatch succeeded") or lower.startswith("opatch failed"):
            continue
        if ";" not in line:
            continue
        patch_id, _, description = line.partition(";")
        patch_id = patch_id.strip()
        # Patch ids are numeric; guard against stray semicolon lines.
        if not patch_id or not patch_id[0].isdigit():
            continue
        rows.append({"PATCH_ID": patch_id, "PATCH_DESCRIPTION": description.strip()})
    return rows


def _local_success_db_details_homes(details) -> list[str]:
    """Return distinct Oracle homes from successfully-inventoried databases."""

    homes: list[str] = []
    seen: set[str] = set()
    for detail in details or []:
        if str(detail.get("collection_status") or "").lower() != "success":
            continue
        home = str(detail.get("oracle_home") or "").strip()
        if home and home not in seen:
            seen.add(home)
            homes.append(home)
    return homes


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DBPatchCollector:
    """Collect ``opatch lspatches`` per distinct Oracle home on a host."""

    def __init__(
        self, runner: SSHRunner | None, logger: logging.Logger | None = None
    ) -> None:
        self.runner = runner
        self.logger = logger or logging.getLogger(__name__)

    def collect_host(
        self,
        db_inventory: DBInventoryRecord,
        host: "HostConfig",
        *,
        enabled: bool = True,
        timeout_seconds: int = 60,
        include_grid_home: bool = True,
        command_executor=None,
    ) -> list[DBPatchRecord]:
        if not enabled:
            return []

        now = _utc_now()
        records: list[DBPatchRecord] = []
        for oracle_home, home_type in self._home_targets(
            db_inventory, include_grid_home
        ):
            owner = self._resolve_owner(host, oracle_home, home_type, db_inventory)
            command = build_opatch_lspatches_command(oracle_home, owner, timeout_seconds)
            result = self._execute(host, oracle_home, owner, command, command_executor)
            records.extend(
                self._records_from_result(
                    db_inventory, oracle_home, home_type, owner, result, now
                )
            )
        return records

    def _home_targets(
        self, db_inventory: DBInventoryRecord, include_grid_home: bool
    ) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        seen: set[str] = set()
        for home in _local_success_db_details_homes(db_inventory.db_resource_details):
            if home and home not in seen:
                seen.add(home)
                targets.append((home, "db"))
        grid_home = (db_inventory.grid_home or "").strip()
        if include_grid_home and grid_home and grid_home not in seen:
            seen.add(grid_home)
            targets.append((grid_home, "grid"))
        return targets

    def _resolve_owner(
        self, host, oracle_home: str, home_type: str, db_inventory: DBInventoryRecord
    ) -> str:
        if home_type == "grid" and (db_inventory.grid_owner or "").strip():
            return db_inventory.grid_owner.strip()
        if self.runner is not None:
            return _resolve_db_owner(self.runner, host, oracle_home)
        return "oracle"

    def _execute(self, host, oracle_home, owner, command, command_executor):
        if command_executor is not None:
            return command_executor(oracle_home, owner, command)
        if self.runner is None:
            raise ValueError("runner is required when command_executor is not supplied")
        return self.runner.run_command(host, command)

    def _records_from_result(
        self, inv, oracle_home, home_type, owner, result, collected_at
    ) -> list[DBPatchRecord]:
        if not result.ok:
            return [
                DBPatchRecord(
                    Cluster=inv.cluster,
                    HOST_NAME=inv.host,
                    ORACLE_HOME=oracle_home,
                    HOME_TYPE=home_type,
                    HOME_OWNER=owner,
                    Collected_At=collected_at,
                    source_host=inv.host,
                    source_address=inv.address,
                    collection_status="failed",
                    collection_error=_opatch_error(result),
                    error_category=_opatch_error_category(result),
                    returncode=getattr(result, "returncode", ""),
                    stdout=getattr(result, "stdout", ""),
                    stderr=getattr(result, "stderr", ""),
                )
            ]
        patches = parse_opatch_lspatches_output(result.stdout)
        if not patches:
            return [
                DBPatchRecord(
                    Cluster=inv.cluster,
                    HOST_NAME=inv.host,
                    ORACLE_HOME=oracle_home,
                    HOME_TYPE=home_type,
                    HOME_OWNER=owner,
                    Collected_At=collected_at,
                    source_host=inv.host,
                    source_address=inv.address,
                    patch_count=0,
                    collection_status="success",
                    collection_error="no_interim_patches",
                )
            ]
        return [
            DBPatchRecord(
                Cluster=inv.cluster,
                HOST_NAME=inv.host,
                ORACLE_HOME=oracle_home,
                HOME_TYPE=home_type,
                HOME_OWNER=owner,
                PATCH_ID=patch["PATCH_ID"],
                PATCH_DESCRIPTION=patch["PATCH_DESCRIPTION"],
                Collected_At=collected_at,
                source_host=inv.host,
                source_address=inv.address,
                patch_count=len(patches),
                collection_status="success",
            )
            for patch in patches
        ]


def _opatch_error(result) -> str:
    stderr = (getattr(result, "stderr", "") or "").strip()
    stdout = (getattr(result, "stdout", "") or "").strip()
    if getattr(result, "timed_out", False):
        return "opatch timed out"
    detail = stderr or stdout or f"opatch exited with {getattr(result, 'returncode', '')}"
    if "sudo" in detail.lower() and (
        "password" in detail.lower() or "not allowed" in detail.lower()
    ):
        return f"{detail}; configure NOPASSWD sudo for the service account"
    return detail


def _opatch_error_category(result) -> str:
    if getattr(result, "timed_out", False):
        return "TIMEOUT"
    combined = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}".lower()
    if "no such file" in combined or "command not found" in combined or "opatch" in combined and "not" in combined:
        return "OPATCH_NOT_FOUND"
    if "sudo" in combined and ("password" in combined or "not allowed" in combined):
        return "SUDO_DENIED"
    return "UNKNOWN"
