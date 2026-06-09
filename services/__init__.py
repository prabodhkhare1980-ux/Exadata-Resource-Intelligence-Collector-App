"""Service layer for the Dash dashboard.

Read-only helpers that load and normalize collector output files. These
helpers must not open SSH connections, call collectors, or import collector
runtime logic.
"""
