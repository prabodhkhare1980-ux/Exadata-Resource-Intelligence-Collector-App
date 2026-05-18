# Exadata Resource Intelligence Collector

A Python 3.11+ collector for Phase 1 Exadata and Oracle RAC infrastructure intelligence. It runs from a local machine or jump server, connects to target nodes over SSH, executes privileged commands with sudo when configured, and stores all collected data locally.

## Phase 1 Scope

This implementation includes:

- YAML inventory loading from `config/clusters.yaml`
- SSH remote execution framework using Python `subprocess`
- SSH stdin-based command streaming only
- Optional sudo execution with `sudo -n bash -s`
- Timeout handling per host
- Per-host logging under `logs/`
- OS collector for:
  - `hostname`
  - `uptime`
  - `df -hPT`
  - `free -m`
  - `lscpu`
  - `/proc/meminfo`
- CSV output: `output/os_inventory.csv`
- JSON output: `output/os_inventory.json`

No ASM, IORM, SQL, remote package installation, SCP, or remote temp scripts are included in Phase 1.

## Project Structure

```text
.
├── collectors/
│   └── os_collector.py
├── config/
│   └── clusters.yaml
├── logs/
├── output/
├── reports/
│   └── writers.py
├── inventory.py
├── logging_setup.py
├── main.py
├── requirements.txt
└── ssh_runner.py
```

## Remote Execution Model

The collector never copies scripts or SQL files to target servers. Each collection payload is streamed into SSH through standard input:

```text
local python subprocess.run(input=<script>)
        |
        v
ssh user@host 'sudo -n bash -s'
        |
        v
remote bash reads commands from stdin
```

When `sudo: true`, the remote command is `sudo -n bash -s`. The `-n` flag prevents interactive password prompts, which keeps runs safe for automation. Configure passwordless sudo for the collector account if privileged execution is required.

## Prerequisites

- Python 3.11 or newer on the local/jump host
- SSH client available on the local/jump host
- SSH key access to each target node
- Optional passwordless sudo on target nodes if `sudo: true`

## Installation

Create and activate a virtual environment, then install dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure Inventory

Edit `config/clusters.yaml`:

```yaml
defaults:
  user: oracle
  port: 22
  sudo: true
  timeout_seconds: 60
  output_dir: output
  logs_dir: logs
  ssh_options:
    - StrictHostKeyChecking=accept-new
    - ServerAliveInterval=15
    - ServerAliveCountMax=2

clusters:
  - name: exadata_cluster_01
    hosts:
      - name: dbnode01
        address: dbnode01.example.com
      - name: dbnode02
        address: dbnode02.example.com
```

Host-level values override defaults. If `address` is omitted, the host `name` is used as the SSH destination.

## Run

Run with the default inventory:

```bash
python main.py --config config/clusters.yaml
```

Enable debug logging:

```bash
python main.py --config config/clusters.yaml --verbose
```

Exit codes:

- `0`: all hosts collected successfully
- `1`: fatal local error, such as invalid configuration
- `2`: collection completed but one or more hosts failed

## Outputs

After a run, review:

- `output/os_inventory.csv` for flattened CSV records
- `output/os_inventory.json` for detailed structured records and raw command sections
- `logs/collector.log` for run-level logging
- `logs/<cluster>_<host>.log` for per-host logging

## Operational Notes

- The SSH command uses `BatchMode=yes` to avoid password prompts.
- Remote connection timeout is controlled by SSH `ConnectTimeout=10` plus each host's `timeout_seconds` subprocess timeout.
- Collection continues when a host fails; failures are written into CSV/JSON with `status=failed`.
- Add future collectors as separate modules under `collectors/` and keep report serialization under `reports/`.
