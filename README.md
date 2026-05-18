# Exadata Resource Intelligence Collector

Python 3.11+ collector for Phase 1 Exadata and Oracle RAC infrastructure inventory. The collector runs from a local workstation or jump server, connects to target hosts with SSH, executes privileged commands with sudo, streams all remote logic through SSH stdin, and stores collected data locally as CSV and JSON.

## Phase 1 scope

Phase 1 includes:

- SSH runner based on `subprocess`
- YAML configuration in `config/clusters.yaml`
- Runtime SSH password authentication
- Per-environment, per-cluster, and per-host `ssh_user` values
- Privileged sudo execution
- OS inventory collection
- CPU and memory collection
- Filesystem capacity collection
- Per-host error handling
- Local CSV and JSON output

Phase 1 intentionally excludes ASM, IORM, SQL, remote package installation, SCP, and copied remote scripts.

## Authentication model

The current supported authentication model is designed for personal IDs with sudo privileges:

- SSH password authentication is required and supported now.
- The collector prompts securely at runtime for each unique `(environment, ssh_user)` combination.
- Password prompts use a no-echo prompt and passwords are cached only in process memory for the current run.
- Passwords are not stored in `config/clusters.yaml` or output files.
- Passwords are not printed in logs.
- Passwords are not passed as subprocess command-line arguments.
- The same prompted password is used for sudo when `sudo_password` is set to `same_as_ssh`.
- Different login IDs can be configured for on-premises Exadata and OCI Exadata.
- `ssh_user` can be set at environment, cluster, or host level. Host overrides cluster, and cluster overrides environment.
- Optional SSH key authentication is represented in the config model for later use, but password authentication is the required mode for Phase 1.

## Configuration

Edit `config/clusters.yaml` before running. The checked-in sample uses a simple YAML subset that the collector can parse with the Python standard library. If you need full YAML features, install the optional YAML extra with `python -m pip install .[yaml]`.

Important fields:

- `environments.<name>.ssh_user`: default personal login ID for an environment such as `onprem` or `oci`.
- `environments.<name>.auth.method`: use `password` for Phase 1.
- `clusters[].ssh_user`: optional cluster-level override.
- `clusters[].hosts[].ssh_user`: optional host-level override.
- `collection.output_dir`: local output directory.
- `collection.ssh.timeout_seconds`: per-host SSH timeout.

Example structure:

```yaml
environments:
  onprem:
    ssh_user: your_onprem_personal_id
    auth:
      method: password
      sudo: true
      sudo_password: same_as_ssh
  oci:
    ssh_user: your_oci_personal_id
    auth:
      method: password
      sudo: true
      sudo_password: same_as_ssh

clusters:
  - name: onprem-rac01
    environment: onprem
    hosts:
      - name: onprem-rac01-db01
        address: onprem-rac01-db01.example.com
  - name: oci-vmcluster01
    environment: oci
    ssh_user: cluster_specific_oci_id
    hosts:
      - name: oci-vmcluster01-db01
        address: 10.0.0.11
```

Do not add passwords to this file.

## Installation

From the repository root:

```bash
python -m pip install .
```

For conventional YAML syntax support:

```bash
python -m pip install '.[yaml]'
```

## Running the collector

```bash
python -m exadata_ric --config config/clusters.yaml
```

or, after installation:

```bash
exadata-ric --config config/clusters.yaml
```

The collector will prompt for SSH passwords at runtime. Output is written under `output/` by default:

```text
output/
  csv/
    os.csv
    cpu_memory.csv
    filesystem.csv
    errors.csv
  json/
    os.json
    cpu_memory.json
    filesystem.json
    errors.json
```

A non-zero exit code means at least one host failed. Successful hosts still produce output, and failed hosts are recorded in `errors.csv` and `errors.json`.

## Remote execution behavior

For each host, the collector:

1. Builds one local Phase 1 shell script from modular collectors.
2. Opens an SSH connection with the configured `ssh_user`.
3. Streams the script through SSH stdin into `sudo -S /bin/sh -s`.
4. Parses tab-delimited output locally.
5. Writes CSV and JSON locally.

The collector does not use SCP, does not create temporary scripts on target servers, and does not install packages on target servers.
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
