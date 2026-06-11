"""Exadata storage-cell inventory across mixed access models.

Storage cells are not reachable the same way in every estate, so this
collector supports three access methods, selected per environment via
``cell_access.method``:

* ``dcli_or_direct`` (on-prem): if ``dcli`` is present, fan out with
  ``dcli -g <cell_group> -l <user> "cellcli -e '...'"``; otherwise discover
  the cell hosts and SSH to each cell directly and run ``cellcli``.
* ``direct_ssh`` (on-prem): always SSH to each discovered cell directly.
* ``exacli`` (OCI ExaCS): cells are reached with ``exacli`` from the DB VM
  using the ``cloud_user_<clustername>`` storage user and the cell IPs in
  ``/etc/oracle/cell/network-config/cellip.ora``.

User fallback: for the on-prem methods each cell/command is attempted with
every user in ``cell_access.users`` (e.g. ``celladmin`` then ``root``) until
one succeeds.

Everything runs as a single command streamed over the existing SSH runner
(``runner.run_command``) — no scripts copied, no temp files, no stored
credentials. All command construction and output parsing are pure functions
so the whole decision tree is unit-testable without a live cell.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from ssh_runner import CommandResult, SSHRunner

if TYPE_CHECKING:
    from inventory import CellAccessConfig, ClusterConfig, HostConfig


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

# Cell attribute fields surfaced as the successful inventory.
CELL_FIELDS = [
    "CELL_NAME",
    "CELL_VERSION",
    "CELL_RELEASE_VERSION",
    "MAKE_MODEL",
    "STATUS",
    "CPU_COUNT",
    "FLASH_CACHE_GB",
    "FLASH_CACHE_MODE",
    "HARD_DISK_GB",
    "FLASH_DISK_GB",
    "HARD_DISK_COUNT",
    "FLASH_DISK_COUNT",
]

CELL_INVENTORY_COLUMNS = [
    "Cluster",
    "source_host",
    "source_address",
    *CELL_FIELDS,
    "cell_access_method",
    "cell_target",
    "cell_user",
    "Collected_At",
    "collection_status",
]

CELL_INVENTORY_ERROR_COLUMNS = [
    "Cluster",
    "source_host",
    "source_address",
    "cell_access_method",
    "cell_target",
    "cell_user",
    "cell_user_attempted",
    "collection_status",
    "collection_error",
    "error_category",
    "dcli_available",
    "cell_group_file_used",
    "cell_hosts_discovered",
    "cell_command",
    "raw_error",
    "Collected_At",
]


@dataclass
class CellInventoryRecord:
    Cluster: str
    source_host: str = ""
    source_address: str = ""
    CELL_NAME: str = ""
    CELL_VERSION: str = ""
    CELL_RELEASE_VERSION: str = ""
    MAKE_MODEL: str = ""
    STATUS: str = ""
    CPU_COUNT: str = ""
    FLASH_CACHE_GB: str = ""
    FLASH_CACHE_MODE: str = ""
    HARD_DISK_GB: str = ""
    FLASH_DISK_GB: str = ""
    HARD_DISK_COUNT: str = ""
    FLASH_DISK_COUNT: str = ""
    cell_access_method: str = ""
    cell_target: str = ""
    cell_user: str = ""
    Collected_At: str = ""
    collection_status: str = "success"
    collection_error: str = ""
    error_category: str = ""
    # Debug / diagnostics.
    dcli_available: str = ""
    cell_group_file_used: str = ""
    cell_hosts_discovered: str = ""
    cell_user_attempted: str = ""
    cell_command: str = ""
    raw_error: str = ""

    def to_csv_row(self) -> dict[str, object]:
        data = asdict(self)
        return {key: data.get(key, "") for key in data}

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Command builders (pure)
# ---------------------------------------------------------------------------

CELLCLI_DETAIL_COMMANDS = {
    "cell": "list cell detail",
    "flashcache": "list flashcache detail",
    "physicaldisk": "list physicaldisk detail",
}


def build_command_check(binary: str) -> str:
    """Probe for an executable without failing the shell when it is absent."""

    return f"command -v {shlex.quote(binary)} 2>/dev/null || true"


def build_exacli_path_probe() -> str:
    """Probe for exacli on PATH and the documented fallback locations."""

    return (
        "command -v exacli 2>/dev/null "
        "|| ls /usr/local/bin/exacli 2>/dev/null "
        "|| ls /usr/bin/exacli 2>/dev/null "
        "|| true"
    )


def build_cat_command(path: str) -> str:
    """Cat a file; non-zero return code signals the file is missing."""

    return f"cat {shlex.quote(path)}"


def build_dcli_cellcli_command(
    cell_group: str, cell_user: str, cellcli_command: str, timeout_seconds: int = 45
) -> str:
    """Build ``dcli -g <group> -l <user> "cellcli -e '<cmd>'"``."""

    inner = f"cellcli -e {shlex.quote(cellcli_command)}"
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


def build_direct_ssh_cellcli_command(
    cell: str, cell_user: str, cellcli_command: str, timeout_seconds: int = 45,
    *, use_sudo: bool = True,
) -> str:
    """Build a nested ``ssh <user>@<cell> "cellcli -e '<cmd>'"`` command.

    Runs from the DB node over the existing SSH session. BatchMode keeps it
    non-interactive (no password prompt); a failed key/login surfaces as an
    auth error rather than hanging. ``use_sudo`` wraps the nested ssh in
    ``sudo -n`` so the DB node's privileged identity (which typically holds
    the cell SSH keys, as ``dcli`` itself is run as root) is used.
    """

    remote = f"cellcli -e {shlex.quote(cellcli_command)}"
    parts = ["timeout", f"{int(timeout_seconds)}s"]
    if use_sudo:
        parts += ["sudo", "-n"]
    parts += [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
        f"{cell_user}@{cell}",
        shlex.quote(remote),
    ]
    return " ".join(parts)


def build_crsctl_cluster_name_command(grid_home: str, grid_owner: str) -> str:
    """Build the sudo/crsctl command that reports the cluster name."""

    path = f"{grid_home}/bin:/usr/bin:/bin"
    return " ".join(
        [
            "sudo",
            "-n",
            "-u",
            shlex.quote(grid_owner),
            "env",
            f"ORACLE_HOME={shlex.quote(grid_home)}",
            f"PATH={shlex.quote(path)}",
            "crsctl",
            "get",
            "cluster",
            "name",
        ]
    )


def build_exacli_command(
    exacli_path: str,
    cell_user: str,
    cell_ip: str,
    cellcli_command: str,
    *,
    use_cookie_jar: bool = True,
    no_prompt: bool = True,
    timeout_seconds: int = 45,
) -> str:
    """Build an ExaCLI invocation for one cell IP."""

    parts = [
        "timeout",
        f"{int(timeout_seconds)}s",
        shlex.quote(exacli_path or "exacli"),
        "-l",
        shlex.quote(cell_user),
        "-c",
        shlex.quote(cell_ip),
    ]
    if use_cookie_jar:
        parts.append("--cookie-jar")
    if no_prompt:
        parts.append("-n")
    parts.extend(["-e", shlex.quote(cellcli_command)])
    return " ".join(parts)


def build_exacli_cookie_refresh_command(
    exacli_path: str,
    cell_user: str,
    cell_ip: str,
    password_command: str,
    *,
    timeout_seconds: int = 60,
    probe_command: str = "list cell",
) -> str:
    """Build the remote shell pipeline that refreshes the ExaCLI cookie jar.

    The pipeline is a single remote bash invocation that:

    1. Captures the cloud_user password from ``password_command``'s stdout
       into a shell variable (the password never enters our app, never
       traverses our SSH connection in plaintext, never lands on argv).
    2. Pipes the password into ``exacli ... --cookie-jar`` (no ``-n``) so
       ExaCLI mints a fresh cookie at the DB VM user's standard location
       (typically ``~/.exacli/cookies``).
    3. Unsets the shell variable.

    Emits ``COOKIE_REFRESH_OK`` on success so the caller can verify cleanly
    without grepping the user's exacli output. ``timeout`` caps the
    blast radius of a stuck password script.
    """

    inner_exacli = " ".join(
        [
            shlex.quote(exacli_path or "exacli"),
            "-l", shlex.quote(cell_user),
            "-c", shlex.quote(cell_ip),
            "--cookie-jar",
            "-e", shlex.quote(probe_command),
        ]
    )
    # The password script and exacli both run inside the same bash -c, so
    # the password never leaves that subshell.
    pipeline = (
        f"_p=$( {password_command} ) || exit 81; "
        f"printf '%s\\n' \"$_p\" | {inner_exacli} > /dev/null 2>&1 || exit 82; "
        f"unset _p; "
        f"echo COOKIE_REFRESH_OK"
    )
    return " ".join(
        [
            "timeout",
            f"{int(timeout_seconds)}s",
            "bash",
            "-c",
            shlex.quote(pipeline),
        ]
    )


def build_exacli_probe_command(
    exacli_path: str, cell_user: str, cell_ip: str, *, timeout_seconds: int = 20
) -> str:
    """Cheap ExaCLI cookie validity probe (``list cell`` is one short row)."""

    return build_exacli_command(
        exacli_path, cell_user, cell_ip, "list cell",
        use_cookie_jar=True, no_prompt=True, timeout_seconds=timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Parsers (pure)
# ---------------------------------------------------------------------------

_DCLI_DETAIL_LINE = re.compile(r"^(?P<cell>\S+?):\s+(?P<attr>[A-Za-z0-9_]+):\s*(?P<value>.*)$")
_CELLCLI_DETAIL_LINE = re.compile(r"^(?P<attr>[A-Za-z0-9_]+):\s+(?P<value>.*)$")
_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")


def parse_command_v(output: str) -> str:
    """Return the first path-looking token from a ``command -v`` probe."""

    for line in (output or "").splitlines():
        token = line.strip()
        if token and (token.startswith("/") or " " not in token):
            return token
    return ""


def parse_cluster_name(output: str) -> str:
    """Parse ``CRS-6724: Current cluster name is <name>`` (or bare name).

    On ExaCS the line is typically ``CRS-6724: Current cluster name is
    'iad3dx02v1'`` -- Oracle wraps the name in single quotes on this CRS
    version. Strip the wrapping quotes so the storage user template (e.g.
    ``cloud_user_{cluster_name}``) gets the bare name, otherwise exacli
    will be invoked as ``cloud_user_'iad3dx02v1'`` and authentication will
    fail with ``No cookies found for cloud_user_'...'@<ip>``.
    """

    def _strip_wrap_quotes(value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            return value[1:-1].strip()
        return value

    for line in (output or "").splitlines():
        match = re.search(r"cluster name is\s+(\S+)", line, re.IGNORECASE)
        if match:
            return _strip_wrap_quotes(match.group(1))
    # crsctl may emit just the name on some versions.
    stripped = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if len(stripped) == 1:
        candidate = _strip_wrap_quotes(stripped[0])
        if candidate and " " not in candidate and "-" not in candidate[:4]:
            return candidate
    return ""


def parse_cell_ips(output: str) -> list[str]:
    """Parse unique cell IPs from a cellip.ora-style file."""

    ips: list[str] = []
    seen: set[str] = set()
    for match in _IPV4.finditer(output or ""):
        ip = match.group(1)
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips


def looks_like_cellip_ora(text: str) -> bool:
    """True when the file is cellip.ora-style (``cell="ip;ip"`` lines)."""

    lowered = (text or "").lower()
    if "cell=" in lowered:
        return True
    # Bare "ip;ip" redundant pairs also indicate the cellip format.
    for line in (text or "").splitlines():
        if ";" in line and _IPV4.search(line):
            return True
    return False


def parse_cellip_ora(text: str) -> list[list[str]]:
    """Parse cellip.ora into one cell per line, each with its redundant IPs.

    A line ``cell="30.117.250.15;30.117.250.16"`` is a single storage cell
    reachable at either IP. Returns ``[["30.117.250.15", "30.117.250.16"], ...]``
    so callers connect to one IP per cell (with the second as fallback)
    instead of treating every IP as a separate cell.
    """

    cells: list[list[str]] = []
    seen_cells: set[tuple[str, ...]] = set()
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        ips: list[str] = []
        for match in _IPV4.finditer(stripped):
            ip = match.group(1)
            if ip not in ips:
                ips.append(ip)
        if not ips:
            continue
        key = tuple(ips)
        if key in seen_cells:
            continue
        seen_cells.add(key)
        cells.append(ips)
    return cells


def parse_cell_group_hosts(output: str) -> list[str]:
    """Parse cell hostnames/IPs from a dcli cell_group file (one per line)."""

    hosts: list[str] = []
    seen: set[str] = set()
    for line in (output or "").splitlines():
        token = line.strip()
        if not token or token.startswith("#"):
            continue
        token = token.split()[0]
        if token and token not in seen:
            seen.add(token)
            hosts.append(token)
    return hosts


def parse_dcli_detail(text: str) -> dict[str, dict[str, str]]:
    """Parse ``dcli "... detail"`` output into ``{cell_host: {attr: value}}``."""

    result: dict[str, dict[str, str]] = {}
    for raw_line in (text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        match = _DCLI_DETAIL_LINE.match(raw_line.strip())
        if not match:
            continue
        result.setdefault(match.group("cell"), {})[match.group("attr")] = match.group("value").strip()
    return result


def parse_dcli_detail_multi(text: str) -> dict[str, list[dict[str, str]]]:
    """Parse dcli detail with multiple objects per cell (split on ``name``)."""

    result: dict[str, list[dict[str, str]]] = {}
    current: dict[str, dict[str, str]] = {}
    for raw_line in (text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        match = _DCLI_DETAIL_LINE.match(raw_line.strip())
        if not match:
            continue
        cell, attr, value = match.group("cell"), match.group("attr"), match.group("value").strip()
        if attr == "name":
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


def parse_cellcli_detail(text: str) -> dict[str, str]:
    """Parse single-cell ``cellcli/exacli "... detail"`` output (no host prefix)."""

    attrs: dict[str, str] = {}
    for raw_line in (text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        match = _CELLCLI_DETAIL_LINE.match(raw_line.strip())
        if not match:
            continue
        attrs[match.group("attr")] = match.group("value").strip()
    return attrs


def parse_cellcli_detail_multi(text: str) -> list[dict[str, str]]:
    """Parse single-cell detail with multiple objects (split on ``name``)."""

    objects: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in (text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        match = _CELLCLI_DETAIL_LINE.match(raw_line.strip())
        if not match:
            continue
        attr, value = match.group("attr"), match.group("value").strip()
        if attr == "name":
            current = {"name": value}
            objects.append(current)
        elif current is not None:
            current[attr] = value
        else:
            current = {attr: value}
            objects.append(current)
    return objects


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


def _physicaldisk_summary(
    objects: list[dict[str, str]],
) -> tuple[float | None, float | None, int, int]:
    hard = flash = 0.0
    hard_found = flash_found = False
    hard_count = flash_count = 0
    for obj in objects:
        size = parse_cell_size_gb(obj.get("physicalSize", "") or obj.get("size", ""))
        disk_type = (obj.get("diskType") or "").lower()
        if "flash" in disk_type:
            flash_count += 1
            if size is not None:
                flash += size
                flash_found = True
        else:
            hard_count += 1
            if size is not None:
                hard += size
                hard_found = True
    return (
        round(hard, 2) if hard_found else None,
        round(flash, 2) if flash_found else None,
        hard_count,
        flash_count,
    )


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def _is_auth_error(result: CommandResult) -> bool:
    combined = f"{result.stdout}\n{result.stderr}".lower()
    return any(
        marker in combined
        for marker in (
            "permission denied",
            "publickey",
            "authentication failed",
            "password",
            "access denied",
            "not authorized",
        )
    )


def _is_exacli_auth_error(result: CommandResult) -> bool:
    combined = f"{result.stdout}\n{result.stderr}".lower()
    return any(
        marker in combined
        for marker in (
            "cookie",
            "not authenticated",
            "authentication required",
            "password",
            "credential",
            "login",
        )
    )


def _raw_error(result: CommandResult) -> str:
    parts = []
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    if stderr:
        parts.append(stderr)
    if stdout and stdout not in parts:
        parts.append(stdout)
    if getattr(result, "error", None):
        parts.append(str(result.error))
    return " | ".join(parts) or f"exit code {result.returncode}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

CommandRunner = Callable[[str], CommandResult]


class CellInventoryCollector:
    """Collect per-cell inventory across dcli / direct-SSH / ExaCLI models."""

    def __init__(self, runner: SSHRunner | None, logger: logging.Logger | None = None) -> None:
        self.runner = runner
        self.logger = logger or logging.getLogger(__name__)

    def collect_cluster(
        self,
        cluster: "ClusterConfig",
        host: "HostConfig",
        access: "CellAccessConfig",
        *,
        grid_home: str = "",
        grid_owner: str = "",
        command_runner: CommandRunner | None = None,
    ) -> list[CellInventoryRecord]:
        if access is None or not access.enabled:
            return []
        run = command_runner or self._default_runner(host)
        ctx = _Ctx(cluster=cluster.name, host=host.name, address=host.address, access=access, run=run)
        if access.method == "exacli":
            return self._collect_exacli(ctx, grid_home, grid_owner)
        return self._collect_onprem(ctx)

    def _default_runner(self, host) -> CommandRunner:
        if self.runner is None:
            raise ValueError("runner is required when command_runner is not supplied")
        return lambda command: self.runner.run_command(host, command)

    # -- on-prem: dcli or direct ssh --------------------------------------

    def _collect_onprem(self, ctx: "_Ctx") -> list[CellInventoryRecord]:
        dcli_path = parse_command_v(ctx.run(build_command_check("dcli")).stdout)
        dcli_available = bool(dcli_path)

        cell_group_used, is_dcli_group, cells = self._discover_cells(ctx)
        flat_targets = [ip for cell in cells for ip in cell]

        force_direct = ctx.access.method == "direct_ssh"

        # `dcli -g <file>` only works with a proper one-host-per-line group
        # file. cellip.ora (cell="ip;ip" lines) is NOT such a file, so we
        # never pass it to dcli -g; those cells go to direct SSH below.
        if dcli_available and is_dcli_group and cell_group_used and not force_direct:
            return self._collect_via_dcli(ctx, cell_group_used, flat_targets, dcli_available)

        if ctx.access.allow_direct_cell_ssh and cells:
            return self._collect_via_direct_ssh(ctx, cells, dcli_available, cell_group_used)

        # Nothing worked: build one diagnostic error record explaining why.
        if not cells:
            error = (
                "no cell targets discovered from "
                f"{', '.join(ctx.access.cell_group_files)} or /etc/hosts"
            )
            category = "CELL_IP_FILE_NOT_FOUND" if cell_group_used else "DCLI_NOT_FOUND"
        elif not ctx.access.allow_direct_cell_ssh:
            error = (
                "cells were discovered but no usable dcli group file is present "
                "and allow_direct_cell_ssh is disabled"
            )
            category = "DCLI_NOT_FOUND"
        else:
            error = "no cell group file found and no cell hosts discovered"
            category = "CELL_IP_FILE_NOT_FOUND"
        return [
            self._error_record(
                ctx,
                method="dcli" if dcli_available and is_dcli_group else "direct_ssh",
                target=",".join(flat_targets),
                user="",
                user_attempted="",
                error=error,
                category=category,
                dcli_available=dcli_available,
                cell_group_used=cell_group_used,
                cell_hosts=flat_targets,
            )
        ]

    def _discover_cells(self, ctx: "_Ctx") -> tuple[str, bool, list[list[str]]]:
        """Discover cell targets from the configured files.

        Returns ``(cell_group_file_used, is_dcli_group, cells)`` where
        ``cells`` is one entry per storage cell, each a list of candidate
        addresses (cellip.ora lines carry two redundant IPs per cell).
        ``is_dcli_group`` is True only for a proper one-host-per-line file
        that can be passed to ``dcli -g``.
        """

        for path in ctx.access.cell_group_files:
            result = ctx.run(build_cat_command(path))
            if not (result.ok and result.stdout.strip()):
                continue
            text = result.stdout
            if "cellip.ora" in path or looks_like_cellip_ora(text):
                cells = parse_cellip_ora(text)
                if cells:
                    return path, False, cells
            else:
                hosts = parse_cell_group_hosts(text)
                if hosts:
                    return path, True, [[h] for h in hosts]
        # Last resort: cell-like entries in /etc/hosts (direct SSH only).
        etc = ctx.run("grep -iE 'cel[l0-9]' /etc/hosts 2>/dev/null || true")
        if etc.ok and etc.stdout.strip():
            hosts = _hosts_from_etc_hosts(etc.stdout)
            if hosts:
                return "", False, [[h] for h in hosts]
        return "", False, []

    def _collect_via_dcli(
        self, ctx: "_Ctx", cell_group: str, cell_hosts: list[str], dcli_available: bool
    ) -> list[CellInventoryRecord]:
        last_error: CommandResult | None = None
        attempted: list[str] = []
        for user in ctx.access.users:
            attempted.append(user)
            commands = {
                kind: build_dcli_cellcli_command(cell_group, user, cmd, ctx.access.timeout_seconds)
                for kind, cmd in CELLCLI_DETAIL_COMMANDS.items()
            }
            cell_res = ctx.run(commands["cell"])
            if not cell_res.ok:
                last_error = cell_res
                if _is_auth_error(cell_res):
                    continue  # try next user
                continue
            cells = parse_dcli_detail(cell_res.stdout)
            if not cells:
                last_error = cell_res
                continue
            flash = parse_dcli_detail_multi(ctx.run(commands["flashcache"]).stdout)
            disks = parse_dcli_detail_multi(ctx.run(commands["physicaldisk"]).stdout)
            records: list[CellInventoryRecord] = []
            for cell_host, attrs in sorted(cells.items()):
                records.append(
                    self._success_record(
                        ctx,
                        method="dcli",
                        target=cell_host,
                        user=user,
                        attrs=attrs,
                        flash=flash.get(cell_host, []),
                        disks=disks.get(cell_host, []),
                        dcli_available=dcli_available,
                        cell_group_used=cell_group,
                        cell_hosts=cell_hosts,
                        command=commands["cell"],
                    )
                )
            return records
        # Every user failed.
        category = "CELL_AUTH" if last_error and _is_auth_error(last_error) else "CELL_COMMAND_FAILED"
        return [
            self._error_record(
                ctx,
                method="dcli",
                target=",".join(cell_hosts),
                user="",
                user_attempted=",".join(attempted),
                error=_raw_error(last_error) if last_error else "dcli command failed",
                category=category,
                dcli_available=dcli_available,
                cell_group_used=cell_group,
                cell_hosts=cell_hosts,
                command=build_dcli_cellcli_command(
                    cell_group, attempted[-1] if attempted else "", CELLCLI_DETAIL_COMMANDS["cell"],
                    ctx.access.timeout_seconds,
                ),
            )
        ]

    def _collect_via_direct_ssh(
        self, ctx: "_Ctx", cells: list[list[str]], dcli_available: bool, cell_group_used: str
    ) -> list[CellInventoryRecord]:
        flat = [ip for cell in cells for ip in cell]
        records: list[CellInventoryRecord] = []
        for candidate_ips in cells:
            records.append(
                self._collect_one_cell_direct(
                    ctx, candidate_ips, dcli_available, cell_group_used, flat
                )
            )
        return records

    def _ssh_cell(self, ctx, ip, user, cellcli_cmd):
        return build_direct_ssh_cellcli_command(
            ip, user, cellcli_cmd, ctx.access.timeout_seconds,
            use_sudo=ctx.access.direct_ssh_use_sudo,
        )

    def _collect_one_cell_direct(
        self, ctx: "_Ctx", candidate_ips: list[str], dcli_available: bool,
        cell_group_used: str, cell_hosts: list[str],
    ) -> CellInventoryRecord:
        """Try each redundant IP x each user until cellcli answers."""

        last_error: CommandResult | None = None
        attempted: list[str] = []
        for ip in candidate_ips:
            for user in ctx.access.users:
                attempted.append(f"{user}@{ip}")
                cmd = self._ssh_cell(ctx, ip, user, CELLCLI_DETAIL_COMMANDS["cell"])
                cell_res = ctx.run(cmd)
                if not cell_res.ok:
                    last_error = cell_res
                    continue
                attrs = parse_cellcli_detail(cell_res.stdout)
                if not attrs:
                    last_error = cell_res
                    continue
                flash = parse_cellcli_detail_multi(
                    ctx.run(self._ssh_cell(ctx, ip, user, CELLCLI_DETAIL_COMMANDS["flashcache"])).stdout
                )
                disks = parse_cellcli_detail_multi(
                    ctx.run(self._ssh_cell(ctx, ip, user, CELLCLI_DETAIL_COMMANDS["physicaldisk"])).stdout
                )
                return self._success_record(
                    ctx,
                    method="direct_ssh",
                    target=ip,
                    user=user,
                    attrs=attrs,
                    flash=flash,
                    disks=disks,
                    dcli_available=dcli_available,
                    cell_group_used=cell_group_used,
                    cell_hosts=cell_hosts,
                    command=cmd,
                )
        category = "CELL_AUTH" if last_error and _is_auth_error(last_error) else "CELL_COMMAND_FAILED"
        return self._error_record(
            ctx,
            method="direct_ssh",
            target=",".join(candidate_ips),
            user="",
            user_attempted=",".join(attempted),
            error=_raw_error(last_error) if last_error else "direct ssh to cell failed",
            category=category,
            dcli_available=dcli_available,
            cell_group_used=cell_group_used,
            cell_hosts=cell_hosts,
            command=self._ssh_cell(
                ctx, candidate_ips[0] if candidate_ips else "",
                ctx.access.users[-1] if ctx.access.users else "",
                CELLCLI_DETAIL_COMMANDS["cell"],
            ),
        )

    # -- OCI ExaCS: exacli ------------------------------------------------

    def _collect_exacli(
        self, ctx: "_Ctx", grid_home: str, grid_owner: str
    ) -> list[CellInventoryRecord]:
        # A. Cluster name -> storage user.
        cluster_name = ""
        if grid_home and grid_owner:
            cn_res = ctx.run(build_crsctl_cluster_name_command(grid_home, grid_owner))
            cluster_name = parse_cluster_name(cn_res.stdout)
        if not cluster_name:
            return [
                self._error_record(
                    ctx, method="exacli", target="", user="", user_attempted="",
                    error=(
                        "could not determine cluster name via crsctl "
                        "(grid_home/grid_owner unknown or crsctl failed)"
                    ),
                    category="CELL_COMMAND_FAILED",
                )
            ]
        # Defensive: refuse to build a storage username that has shell-special
        # or stray-quote characters — this is what produced the
        # `cloud_user_'iad3dx02v1'` regression where exacli could not find a
        # matching cookie.
        if any(ch in cluster_name for ch in (" ", "\t", "'", '"', "$", "`")):
            return [
                self._error_record(
                    ctx, method="exacli", target="", user="", user_attempted="",
                    error=(
                        f"refusing to use cluster name with stray characters: {cluster_name!r}. "
                        "Check `crsctl get cluster name` output on the DB VM."
                    ),
                    category="CELL_COMMAND_FAILED",
                )
            ]
        cell_user = ctx.access.exacli_user_template.format(cluster_name=cluster_name)

        # B. Cell IPs.
        ip_res = ctx.run(build_cat_command(ctx.access.cell_ip_file))
        if not ip_res.ok or not ip_res.stdout.strip():
            return [
                self._error_record(
                    ctx, method="exacli", target="", user=cell_user, user_attempted=cell_user,
                    error=f"cell IP file not readable: {ctx.access.cell_ip_file}: {_raw_error(ip_res)}",
                    category="CELL_IP_FILE_NOT_FOUND",
                )
            ]
        # cellip.ora groups two redundant IPs per cell; query each cell once
        # (primary IP, second as fallback) rather than once per IP.
        cells = parse_cellip_ora(ip_res.stdout)
        if not cells:
            return [
                self._error_record(
                    ctx, method="exacli", target="", user=cell_user, user_attempted=cell_user,
                    error=f"no cell IPs parsed from {ctx.access.cell_ip_file}",
                    category="CELL_IP_FILE_NOT_FOUND",
                )
            ]
        flat_ips = [ip for cell in cells for ip in cell]

        # C. exacli binary.
        exacli_path = parse_command_v(ctx.run(build_exacli_path_probe()).stdout)
        if not exacli_path:
            return [
                self._error_record(
                    ctx, method="exacli", target=",".join(flat_ips), user=cell_user,
                    user_attempted=cell_user,
                    error="exacli not found on PATH or in /usr/local/bin, /usr/bin",
                    category="EXACLI_NOT_FOUND", cell_hosts=flat_ips,
                )
            ]

        # D. Per-cell collection. ExaCLI cookies are PER-CELL (one cookie per
        # cluster_name x cell_ip pair), so each cell does its own
        # try-then-refresh-then-retry rather than relying on a single cluster
        # probe. The password_command runs at most once per cell that needs
        # a new cookie, and never enters this app's process.
        records: list[CellInventoryRecord] = []
        for candidate_ips in cells:
            records.append(
                self._collect_one_cell_exacli(
                    ctx, exacli_path, cell_user, candidate_ips, flat_ips,
                )
            )
        return records

    def _refresh_cookie_for_ip(
        self, ctx: "_Ctx", exacli_path: str, cell_user: str, ip: str,
    ) -> str:
        """Mint a fresh ExaCLI cookie for a single ``(cell_user, ip)`` pair.

        Returns a short diagnostic string describing the outcome (used as a
        suffix in the per-cell ``raw_error``/log line). Never raises and
        never logs the password.
        """

        if not (ctx.access.cookie_refresh and ctx.access.password_command):
            return "cookie_expired_no_refresh_configured"

        refresh_cmd = build_exacli_cookie_refresh_command(
            exacli_path, cell_user, ip, ctx.access.password_command,
            timeout_seconds=max(ctx.access.timeout_seconds, 60),
        )
        refresh = ctx.run(refresh_cmd)
        if refresh.ok and "COOKIE_REFRESH_OK" in (refresh.stdout or ""):
            self.logger.info("ExaCLI cookie refreshed for user=%s via %s", cell_user, ip)
            return "cookie_refreshed"
        # Exit codes 81/82 are emitted by build_exacli_cookie_refresh_command
        # for password-fetch and exacli-pipe failures respectively. Surface
        # them as stable, parseable suffixes so operators can distinguish a
        # broken password script from a wrong password.
        rc = getattr(refresh, "returncode", "")
        if rc == 81:
            return "cookie_refresh_failed:password_command_failed"
        if rc == 82:
            return "cookie_refresh_failed:exacli_rejected_password"
        # Don't surface the refresh command body (it contains the password
        # script invocation) — only the captured stderr suffix is useful.
        return f"cookie_refresh_failed:{(refresh.stderr or '').strip()[:120]}"

    def _collect_one_cell_exacli(
        self, ctx: "_Ctx", exacli_path: str, cell_user: str,
        candidate_ips: list[str], all_ips: list[str],
    ) -> CellInventoryRecord:
        def exacli(ip: str, cmd: str) -> str:
            return build_exacli_command(
                exacli_path, cell_user, ip, cmd,
                use_cookie_jar=ctx.access.use_cookie_jar,
                no_prompt=ctx.access.no_prompt,
                timeout_seconds=ctx.access.timeout_seconds,
            )

        last_res: CommandResult | None = None
        last_cmd = ""
        refresh_diag_per_ip: dict[str, str] = {}
        for ip in candidate_ips:
            cell_cmd = exacli(ip, CELLCLI_DETAIL_COMMANDS["cell"])
            last_cmd = cell_cmd
            cell_res = ctx.run(cell_cmd)

            # ExaCLI cookies are per-cell. If THIS cell's cookie is missing or
            # expired, try the refresh once, then retry. Other cells' cookies
            # may still be valid -- we don't touch them.
            if not cell_res.ok and _is_exacli_auth_error(cell_res):
                diag = self._refresh_cookie_for_ip(ctx, exacli_path, cell_user, ip)
                refresh_diag_per_ip[ip] = diag
                if diag == "cookie_refreshed":
                    cell_res = ctx.run(cell_cmd)

            last_res = cell_res
            if not cell_res.ok:
                if _is_exacli_auth_error(cell_res):
                    diag = refresh_diag_per_ip.get(ip, "")
                    msg = (
                        "exacli authentication required. Configure "
                        "cell_access.cookie_refresh + password_command, "
                        "or run an initial `exacli ... --cookie-jar` "
                        "login manually on the DB VM."
                    )
                    if diag and diag not in ("cookie_ok", "cookie_refreshed"):
                        msg = f"{msg} [cookie: {diag}]"
                    return self._error_record(
                        ctx, method="exacli", target=ip, user=cell_user, user_attempted=cell_user,
                        error=msg,
                        category="EXACLI_AUTH_REQUIRED", cell_hosts=all_ips, command=cell_cmd,
                        raw_error=_raw_error(cell_res),
                    )
                continue  # connection issue on this IP — try the redundant one
            attrs = parse_cellcli_detail(cell_res.stdout)
            if not attrs:
                return self._error_record(
                    ctx, method="exacli", target=ip, user=cell_user, user_attempted=cell_user,
                    error="exacli returned no parseable cell detail",
                    category="PARSE_ERROR", cell_hosts=all_ips, command=cell_cmd,
                    raw_error=cell_res.stdout.strip(),
                )
            flash = parse_cellcli_detail_multi(ctx.run(exacli(ip, CELLCLI_DETAIL_COMMANDS["flashcache"])).stdout)
            disks = parse_cellcli_detail_multi(ctx.run(exacli(ip, CELLCLI_DETAIL_COMMANDS["physicaldisk"])).stdout)
            return self._success_record(
                ctx, method="exacli", target=ip, user=cell_user, attrs=attrs,
                flash=flash, disks=disks, cell_hosts=all_ips, command=cell_cmd,
            )
        return self._error_record(
            ctx, method="exacli", target=",".join(candidate_ips), user=cell_user,
            user_attempted=cell_user,
            error=_raw_error(last_res) if last_res else "exacli failed for all cell IPs",
            category="CELL_COMMAND_FAILED", cell_hosts=all_ips, command=last_cmd,
        )

    # -- record builders --------------------------------------------------

    def _success_record(
        self, ctx, *, method, target, user, attrs, flash, disks,
        dcli_available=None, cell_group_used="", cell_hosts=None, command="",
    ) -> CellInventoryRecord:
        flash_gb, flash_mode = _flashcache_summary(flash)
        hard_gb, flash_disk_gb, hard_count, flash_count = _physicaldisk_summary(disks)
        return CellInventoryRecord(
            Cluster=ctx.cluster,
            source_host=ctx.host,
            source_address=ctx.address,
            CELL_NAME=attrs.get("name", target),
            CELL_VERSION=attrs.get("cellVersion", ""),
            CELL_RELEASE_VERSION=attrs.get("releaseVersion", ""),
            MAKE_MODEL=attrs.get("makeModel", ""),
            STATUS=attrs.get("status", ""),
            CPU_COUNT=attrs.get("cpuCount", ""),
            FLASH_CACHE_GB="" if flash_gb is None else f"{flash_gb}",
            FLASH_CACHE_MODE=flash_mode,
            HARD_DISK_GB="" if hard_gb is None else f"{hard_gb}",
            FLASH_DISK_GB="" if flash_disk_gb is None else f"{flash_disk_gb}",
            HARD_DISK_COUNT=str(hard_count) if hard_count else "",
            FLASH_DISK_COUNT=str(flash_count) if flash_count else "",
            cell_access_method=method,
            cell_target=target,
            cell_user=user,
            Collected_At=_utc_now(),
            collection_status="success",
            dcli_available=_bool_str(dcli_available),
            cell_group_file_used=cell_group_used,
            cell_hosts_discovered=",".join(cell_hosts or []),
            cell_user_attempted=user,
            cell_command=command,
        )

    def _error_record(
        self, ctx, *, method, target, user, user_attempted, error, category,
        dcli_available=None, cell_group_used="", cell_hosts=None, command="", raw_error="",
    ) -> CellInventoryRecord:
        return CellInventoryRecord(
            Cluster=ctx.cluster,
            source_host=ctx.host,
            source_address=ctx.address,
            cell_access_method=method,
            cell_target=target,
            cell_user=user,
            Collected_At=_utc_now(),
            collection_status="failed",
            collection_error=error,
            error_category=category,
            dcli_available=_bool_str(dcli_available),
            cell_group_file_used=cell_group_used,
            cell_hosts_discovered=",".join(cell_hosts or []),
            cell_user_attempted=user_attempted,
            cell_command=command,
            raw_error=raw_error or error,
        )


@dataclass
class _Ctx:
    cluster: str
    host: str
    address: str
    access: "CellAccessConfig"
    run: CommandRunner


def _bool_str(value) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def _hosts_from_etc_hosts(text: str) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # /etc/hosts: <ip> <name> [aliases...]; prefer a cell-looking name.
        for token in parts[1:]:
            if re.search(r"cel[l0-9]", token, re.IGNORECASE) and token not in seen:
                seen.add(token)
                hosts.append(token)
                break
    return hosts
