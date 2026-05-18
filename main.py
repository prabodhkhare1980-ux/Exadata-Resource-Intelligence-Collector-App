"""Command-line entry point for Exadata Resource Intelligence Collector."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from collectors.os_collector import OSCollector
from inventory import Inventory, load_inventory
from logging_setup import configure_logging, host_logger
from reports.writers import write_os_csv, write_os_json
from ssh_runner import SSHRunner

LOGGER = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Collect Phase 1 OS capacity intelligence from Exadata/RAC nodes."
    )
    parser.add_argument(
        "--config",
        default="config/clusters.yaml",
        help="Path to YAML inventory file. Default: config/clusters.yaml",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging.",
    )
    parser.add_argument(
        "--show-inventory",
        action="store_true",
        help="Print resolved inventory details for each host and exit.",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Run lightweight SSH preflight (hostname only) for each host.",
    )
    return parser.parse_args(argv)


def run(inventory: Inventory) -> int:
    """Run collection for all clusters in the inventory."""

    inventory.output_dir.mkdir(parents=True, exist_ok=True)
    inventory.logs_dir.mkdir(parents=True, exist_ok=True)

    runner = SSHRunner(logging.getLogger("ssh_runner"))
    collector = OSCollector(runner, logging.getLogger("collectors.os"))
    records = []

    for cluster in inventory.clusters:
        LOGGER.info("Collecting cluster %s (%s hosts)", cluster.name, len(cluster.hosts))
        host_loggers = {
            host.name: host_logger(inventory.logs_dir, f"{cluster.name}_{host.name}")
            for host in cluster.hosts
        }
        records.extend(collector.collect_cluster(cluster, host_loggers))

    csv_path = write_os_csv(records, inventory.output_dir)
    json_path = write_os_json(records, inventory.output_dir)
    LOGGER.info("Wrote CSV report: %s", csv_path)
    LOGGER.info("Wrote JSON report: %s", json_path)

    failures = [record for record in records if record.status != "ok"]
    if failures:
        LOGGER.warning("Collection completed with %s host failure(s).", len(failures))
        return 2
    LOGGER.info("Collection completed successfully for %s host(s).", len(records))
    return 0


def show_inventory(inventory: Inventory) -> int:
    """Print resolved per-host inventory details."""

    for cluster in inventory.clusters:
        for host in cluster.hosts:
            print(
                f"{cluster.name} {cluster.environment} {host.name} {host.address} "
                f"ssh_user={host.user} auth_method={host.auth_method} "
                f"strict_host_key_checking={host.strict_host_key_checking}"
            )
    return 0


def preflight(inventory: Inventory) -> int:
    """Run preflight connectivity test (hostname only) for each host."""

    runner = SSHRunner(logging.getLogger("ssh_runner"))
    failures = 0
    for cluster in inventory.clusters:
        LOGGER.info("Preflight cluster %s (%s hosts)", cluster.name, len(cluster.hosts))
        for host in cluster.hosts:
            result = runner.run_script(host, "hostname\n")
            if result.ok:
                LOGGER.info("Preflight passed for %s: %s", host.name, result.stdout.strip())
            else:
                failures += 1
                error = result.error or result.stderr.strip() or f"SSH exited with {result.returncode}"
                LOGGER.error("Preflight failed for %s: %s", host.name, error)
    return 2 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """Program entry point."""

    args = parse_args(argv)
    try:
        inventory = load_inventory(args.config)
        configure_logging(inventory.logs_dir, args.verbose)
        LOGGER.info("Loaded inventory: %s", Path(args.config))
        if args.show_inventory:
            return show_inventory(inventory)
        if args.preflight:
            return preflight(inventory)
        return run(inventory)
    except Exception as exc:  # noqa: BLE001 - CLI should produce readable fatal errors.
        logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")
        logging.getLogger(__name__).exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
