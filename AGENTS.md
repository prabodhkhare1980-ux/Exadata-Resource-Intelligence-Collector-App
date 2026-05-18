# Exadata Resource Intelligence Collector

## Project Goals

Build a Python-based Exadata infrastructure intelligence and capacity collection system.

The application must:

- Run from a local machine or jump server
- Connect remotely using SSH
- Use privileged sudo execution
- NEVER copy scripts or SQL files to target servers
- Execute all commands remotely through SSH stdin
- Store all collected data locally
- Support Exadata and Oracle RAC environments

## Authentication Design

Current Phase 1 authentication requirements:

- Operators connect with their personal login IDs.
- Operators have sudo privileges on target Exadata servers.
- SSH password authentication is required now.
- SSH passwords must be prompted securely at runtime with `getpass` or an equivalent no-echo mechanism.
- Passwords must never be stored in `config/clusters.yaml`, other config files, output files, or logs.
- Passwords must never be passed on command lines or printed in exceptions.
- The same prompted password may be reused in memory for sudo when `sudo_password: same_as_ssh` is configured.
- Login IDs may differ between on-premises Exadata and OCI Exadata.
- `ssh_user` must be overridable at environment, cluster, and host level, with the most specific value winning.
- Optional SSH key authentication may be added or enabled later, but password authentication must remain supported.

Recommended config model:

- Define environment defaults under `environments.<name>.ssh_user`.
- Override the user for a cluster with `clusters[].ssh_user` when needed.
- Override the user for a single host with `clusters[].hosts[].ssh_user` when needed.
- Use `auth.method: password` for the current required authentication mode.
- Do not add password fields to config examples or schemas.

## Coding Standards

- Use Python 3.11+
- Prefer standard Python libraries
- Modular architecture
- Clear logging
- Timeout handling required
- Per-host error handling required
- CSV + JSON output required
- HTML dashboard later

## Remote Execution Rules

DO:
- Stream commands over SSH
- Use subprocess
- Use stdin-based execution
- Prompt locally for SSH passwords at runtime
- Send sudo input only over the encrypted SSH session when sudo requires a password

DO NOT:
- SCP scripts
- Create temp scripts on remote servers
- Install packages on remote servers
- Store passwords in config files
- Log passwords or include passwords in subprocess command arguments

## Initial Scope

Phase 1 only:
- SSH runner
- YAML config
- Runtime SSH password authentication
- Per-environment, per-cluster, and per-host `ssh_user` resolution
- OS collector
- Filesystem collector
- CPU/memory collector
- CSV output
- JSON output

Authentication rule:
On-prem Exadata login may use plain enterprise ID such as al44002, not domain-prefixed us\al44002. OCI Exadata may use a different ID such as AN697937AD. The app must resolve ssh_user by host override, then cluster override, then environment default.
No ASM/IORM/SQL yet.
