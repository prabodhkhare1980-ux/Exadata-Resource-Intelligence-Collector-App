"""Tests for the PDB inventory dashboard normalizers."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.normalizers import (  # noqa: E402
    build_pdb_cluster_rollup,
    build_pdbs_per_cdb,
    normalize_pdb_inventory,
)


def _sample_pdbs() -> pd.DataFrame:
    # Two clusters, three CDBs, one CDB has 4 PDBs (license review).
    # DCPSC1PF is non-CDB (collection_error=no_pluggable_databases, PDB empty).
    return pd.DataFrame(
        [
            # Cluster onprem-dc04dx26 CDB DOFLP7PD x 3 PDBs (RAC node 1)
            {"Cluster": "onprem-dc04dx26", "HOST_NAME": "db01", "CDB_NAME": "DOFLP7PD",
             "PDB_NAME": "TOPOD", "CON_ID": 3, "OPEN_MODE": "READ WRITE",
             "RESTRICTED": "NO", "TOTAL_SIZE_GB": 1331.67,
             "collection_status": "success"},
            {"Cluster": "onprem-dc04dx26", "HOST_NAME": "db01", "CDB_NAME": "DOFLP7PD",
             "PDB_NAME": "TOPOT", "CON_ID": 4, "OPEN_MODE": "READ WRITE",
             "RESTRICTED": "NO", "TOTAL_SIZE_GB": 1372.66,
             "collection_status": "success"},
            {"Cluster": "onprem-dc04dx26", "HOST_NAME": "db01", "CDB_NAME": "DOFLP7PD",
             "PDB_NAME": "TOPOU", "CON_ID": 5, "OPEN_MODE": "READ WRITE",
             "RESTRICTED": "NO", "TOTAL_SIZE_GB": 1717.88,
             "collection_status": "success"},
            # Same CDB seen on RAC node 2 (should dedupe).
            {"Cluster": "onprem-dc04dx26", "HOST_NAME": "db02", "CDB_NAME": "DOFLP7PD",
             "PDB_NAME": "TOPOD", "CON_ID": 3, "OPEN_MODE": "READ WRITE",
             "RESTRICTED": "NO", "TOTAL_SIZE_GB": 1331.67,
             "collection_status": "success"},
            # Cluster onprem-dc04dx26 CDB DAMGLDPD x 1 PDB
            {"Cluster": "onprem-dc04dx26", "HOST_NAME": "db01", "CDB_NAME": "DAMGLDPD",
             "PDB_NAME": "GOLDAM", "CON_ID": 3, "OPEN_MODE": "READ WRITE",
             "RESTRICTED": "NO", "TOTAL_SIZE_GB": 937.05,
             "collection_status": "success"},
            # Cluster oci CDB DOFLPCPD with 4 PDBs (license review).
            {"Cluster": "oci-cluster", "HOST_NAME": "ocidb1", "CDB_NAME": "DOFLPCPD",
             "PDB_NAME": "EDIBR2Q", "CON_ID": 3, "OPEN_MODE": "READ WRITE",
             "RESTRICTED": "NO", "TOTAL_SIZE_GB": 56.34,
             "collection_status": "success"},
            {"Cluster": "oci-cluster", "HOST_NAME": "ocidb1", "CDB_NAME": "DOFLPCPD",
             "PDB_NAME": "EDITI2D", "CON_ID": 4, "OPEN_MODE": "READ WRITE",
             "RESTRICTED": "NO", "TOTAL_SIZE_GB": 88.34,
             "collection_status": "success"},
            {"Cluster": "oci-cluster", "HOST_NAME": "ocidb1", "CDB_NAME": "DOFLPCPD",
             "PDB_NAME": "EDITI2Q", "CON_ID": 5, "OPEN_MODE": "MOUNTED",
             "RESTRICTED": None, "TOTAL_SIZE_GB": 414.34,
             "collection_status": "success"},
            {"Cluster": "oci-cluster", "HOST_NAME": "ocidb1", "CDB_NAME": "DOFLPCPD",
             "PDB_NAME": "EDITI3X", "CON_ID": 6, "OPEN_MODE": "READ WRITE",
             "RESTRICTED": "YES", "TOTAL_SIZE_GB": 100.0,
             "collection_status": "success"},
            # Non-CDB informational row (should be filtered).
            {"Cluster": "onprem-dc04dx26", "HOST_NAME": "db01", "CDB_NAME": "DCPSC1PF",
             "PDB_NAME": "", "CON_ID": None, "OPEN_MODE": None,
             "RESTRICTED": None, "TOTAL_SIZE_GB": None,
             "collection_status": "success",
             "collection_error": "no_pluggable_databases"},
        ]
    )


def test_normalize_pdb_inventory_drops_non_cdb_rows() -> None:
    table = normalize_pdb_inventory(_sample_pdbs())
    # 5 distinct PDBs total: TOPOD/TOPOT/TOPOU/GOLDAM (onprem) + EDIBR2Q/EDITI2D/EDITI2Q/EDITI3X (oci) = 8
    assert "" not in set(table["pdb_name"].astype(str).str.strip().unique())
    assert "DCPSC1PF" not in set(table["cdb_name"])  # non-CDB filtered out


def test_normalize_pdb_inventory_dedupes_rac_duplicate_pdb_rows() -> None:
    table = normalize_pdb_inventory(_sample_pdbs())
    onprem_dofl = table[
        (table["cluster"] == "onprem-dc04dx26") & (table["cdb_name"] == "DOFLP7PD")
    ]
    # 3 distinct PDBs (TOPOD/TOPOT/TOPOU), not 4 (RAC duplicate dropped).
    assert sorted(onprem_dofl["pdb_name"].tolist()) == ["TOPOD", "TOPOT", "TOPOU"]


def test_normalize_pdb_inventory_handles_empty() -> None:
    table = normalize_pdb_inventory(pd.DataFrame())
    assert table.empty
    assert "total_size_gb" in table.columns
    assert "pdb_name" in table.columns


def test_build_pdb_cluster_rollup() -> None:
    rollup = build_pdb_cluster_rollup(normalize_pdb_inventory(_sample_pdbs()))
    by_cluster = rollup.set_index("cluster")

    onprem = by_cluster.loc["onprem-dc04dx26"]
    assert onprem["cdbs"] == 2          # DOFLP7PD + DAMGLDPD
    assert onprem["pdbs"] == 4          # 3 + 1
    assert onprem["pdbs_per_cdb_max"] == 3  # DOFLP7PD has 3 PDBs
    assert onprem["restricted_pdbs"] == 0

    oci = by_cluster.loc["oci-cluster"]
    assert oci["cdbs"] == 1
    assert oci["pdbs"] == 4
    assert oci["pdbs_per_cdb_max"] == 4
    assert oci["mounted_pdbs"] == 1     # EDITI2Q
    assert oci["restricted_pdbs"] == 1  # EDITI3X


def test_build_pdbs_per_cdb_flags_over_three() -> None:
    per_cdb = build_pdbs_per_cdb(normalize_pdb_inventory(_sample_pdbs()))
    by_cdb = per_cdb.set_index(["cluster", "cdb_name"])

    # DOFLPCPD has 4 PDBs -> flagged for license review.
    assert by_cdb.loc[("oci-cluster", "DOFLPCPD"), "pdb_count"] == 4
    assert "REVIEW" in by_cdb.loc[("oci-cluster", "DOFLPCPD"), "license_flag"]

    # DOFLP7PD has 3 PDBs -> exactly at the threshold, OK.
    assert by_cdb.loc[("onprem-dc04dx26", "DOFLP7PD"), "pdb_count"] == 3
    assert by_cdb.loc[("onprem-dc04dx26", "DOFLP7PD"), "license_flag"] == "OK"


def test_build_pdb_rollups_handle_empty() -> None:
    assert build_pdb_cluster_rollup(pd.DataFrame()).empty
    assert build_pdbs_per_cdb(pd.DataFrame()).empty
