"""Command-line interface."""

from __future__ import annotations

import argparse
import logging
import sys

from .auth import CredentialProvider
from .config import ConfigError, load_config
from .output import merge_results, write_results
from .runner import collect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exadata Resource Intelligence Collector")
    parser.add_argument("--config", default="config/clusters.yaml", help="Path to cluster YAML configuration")
    parser.add_argument("--output-dir", help="Override output directory from config")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        config = load_config(args.config)
    except (ConfigError, OSError) as exc:
        logging.getLogger(__name__).error("failed to load config: %s", exc)
        return 2

    if args.output_dir:
        config = type(config)(output_dir=type(config.output_dir)(args.output_dir), hosts=config.hosts)

    results, errors = collect(config, CredentialProvider())
    grouped = merge_results(results)
    write_results(config.output_dir, grouped, errors)

    if errors:
        logging.getLogger(__name__).warning("collection completed with %d host error(s)", len(errors))
        return 1
    logging.getLogger(__name__).info("collection completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
