"""Standalone driver for the storage-cell inventory collector.

Runs *only* the cell collector against one (or all) cluster(s) so you can
iterate on cell access without running the full pipeline. It prints a
per-cell summary to the console (target / method / user / status / error
category / error) and — unless ``--no-write`` — writes the same
``output/cell_inventory*.{csv,json}`` files the full run produces.

Examples
--------
::

    python -m scripts.run_cell_inventory --config config/clusters.local.yaml
    python -m scripts.run_cell_inventory --config config/clusters.local.yaml --cluster onprem-rac01
    python -m scripts.run_cell_inventory --config config/clusters.local.yaml --debug-ssh --no-write

This is a diagnostic tool: it never copies scripts, never creates temp
files on targets, and stores no credentials — same rules as the collector.
"""

from __future__ import annotations

import argparse
import logging
import sys

from collectors.cell_inventory_collector import CellInventoryCollector
from inventory import CellAccessConfig, load_inventory
from reports.writers import (
    write_cell_inventory_csv,
    write_cell_inventory_errors_csv,
    write_cell_inventory_errors_json,
    write_cell_inventory_json,
)
from ssh_runner import SSHRunner

LOGGER = logging.getLogger("scripts.run_cell_inventory")

# Light Grid-environment probe (oratab +ASM line -> grid_home, then the
# owner of crsctl). Only needed so the ExaCLI method can resolve the cluster
# name via ``crsctl get cluster name``; harmless for the on-prem methods.
_GRID_ENV_CMD = (
    "grid_oratab=$(awk -F: '/^\\+ASM/ {print $1 \"|\" $2; exit}' /etc/oratab 2>/dev/null || true); "
    "grid_home=; grid_owner=; "
    'if [ "$grid_oratab" != "" ]; then grid_home=${grid_oratab#*|}; fi; '
    'if [ -n "$grid_home" ]; then grid_owner=$(stat -c \'%U\' "$grid_home/bin/crsctl" 2>/dev/null || true); fi; '
    "printf '%s|%s\\n' \"$grid_home\" \"$grid_owner\""
)


def _discover_grid_env(runner: SSHRunner, host) -> tuple[str, str]:
    try:
        result = runner.run_command(host, _GRID_ENV_CMD)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Grid env probe failed on %s: %s", host.name, exc)
        return "", ""
    grid_home, _, grid_owner = (result.stdout or "").strip().partition("|")
    return grid_home.strip(), grid_owner.strip()


def _print_summary(records) -> None:
    if not records:
        print("\nNo cell records produced (cell inventory disabled, or no clusters matched).")
        return
    ok = [r for r in records if str(r.collection_status).lower() == "success"]
    bad = [r for r in records if str(r.collection_status).lower() != "success"]
    print(f"\n=== Cell inventory: {len(ok)} succeeded, {len(bad)} failed ===")
    width = max((len(str(r.cell_target)) for r in records), default=6)
    for r in records:
        status = "OK " if r in ok else "ERR"
        line = (
            f"[{status}] cluster={r.Cluster} target={str(r.cell_target):<{width}} "
            f"method={r.cell_access_method or '-'} user={r.cell_user or r.cell_user_attempted or '-'}"
        )
        if r in ok:
            line += f" cell={r.CELL_NAME} ver={r.CELL_RELEASE_VERSION or r.CELL_VERSION}"
        else:
            line += f" category={r.error_category} :: {r.collection_error}"
        print(line)
    if bad:
        print("\n--- failure detail (first 5) ---")
        for r in bad[:5]:
            print(f"\ntarget={r.cell_target} category={r.error_category}")
            print(f"  dcli_available     = {r.dcli_available}")
            print(f"  cell_group_used    = {r.cell_group_file_used}")
            print(f"  cell_hosts_found   = {r.cell_hosts_discovered}")
            print(f"  users_attempted    = {r.cell_user_attempted}")
            print(f"  command            = {r.cell_command}")
            print(f"  raw_error          = {r.raw_error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.run_cell_inventory",
        description="Run only the storage-cell inventory collector (diagnostic).",
    )
    parser.add_argument("--config", required=True, help="Path to the inventory YAML.")
    parser.add_argument("--cluster", default=None, help="Only this cluster (by name).")
    parser.add_argument("--debug-ssh", action="store_true", help="Log the SSH commands run.")
    parser.add_argument("--no-write", action="store_true", help="Print only; do not write output files.")
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG-level logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    inventory = load_inventory(args.config)
    if not inventory.cell_inventory_enabled:
        print("collection.cell_inventory.enabled is false — nothing to do.")
        return 0

    clusters = inventory.clusters
    if args.cluster:
        clusters = [c for c in clusters if c.name == args.cluster]
        if not clusters:
            print(f"No cluster named '{args.cluster}' in {args.config}.", file=sys.stderr)
            return 2

    runner = SSHRunner(logging.getLogger("ssh_runner"), debug_ssh=args.debug_ssh)
    collector = CellInventoryCollector(runner, logger=logging.getLogger("collectors.cell_inventory"))

    records = []
    for cluster in clusters:
        if not cluster.hosts:
            continue
        host = cluster.hosts[0]
        access = inventory.cell_access_by_environment.get(cluster.environment) or CellAccessConfig()
        grid_home, grid_owner = "", ""
        if access.method == "exacli":
            grid_home, grid_owner = _discover_grid_env(runner, host)
            LOGGER.info(
                "Cluster %s: exacli via %s (grid_home=%s grid_owner=%s)",
                cluster.name, host.name, grid_home or "?", grid_owner or "?",
            )
        else:
            LOGGER.info("Cluster %s: method=%s via %s", cluster.name, access.method, host.name)
        try:
            records.extend(
                collector.collect_cluster(
                    cluster, host, access, grid_home=grid_home, grid_owner=grid_owner
                )
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Cell collection raised for cluster %s: %s", cluster.name, exc)

    _print_summary(records)

    if not args.no_write:
        out = inventory.output_dir
        write_cell_inventory_csv(records, out)
        write_cell_inventory_json(records, out)
        write_cell_inventory_errors_csv(records, out)
        write_cell_inventory_errors_json(records, out)
        print(f"\nWrote cell_inventory.{{csv,json}} and cell_inventory_errors.{{csv,json}} to {out}/")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
