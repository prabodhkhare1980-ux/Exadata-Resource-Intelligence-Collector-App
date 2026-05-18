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

DO NOT:
- SCP scripts
- Create temp scripts on remote servers
- Install packages on remote servers

## Initial Scope

Phase 1 only:
- SSH runner
- YAML config
- OS collector
- Filesystem collector
- CPU/memory collector
- CSV output

No ASM/IORM/SQL yet.
