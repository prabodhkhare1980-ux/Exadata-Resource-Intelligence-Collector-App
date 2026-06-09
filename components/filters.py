"""Helpers for shared filter handling across pages."""

from __future__ import annotations

import pandas as pd


def cluster_options_from_outputs(*frames: pd.DataFrame) -> list[dict[str, str]]:
    """Build a deduplicated list of cluster dropdown options."""

    clusters: set[str] = set()
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in ("cluster", "Cluster"):
            if column in frame.columns:
                values = frame[column].dropna().astype(str).str.strip()
                clusters.update(value for value in values if value)
                break
    return [{"label": cluster, "value": cluster} for cluster in sorted(clusters)]


def apply_cluster_filter(df: pd.DataFrame, selected: list[str] | None) -> pd.DataFrame:
    """Filter a dataframe to the selected clusters, if any."""

    if df is None or df.empty or not selected:
        return df if df is not None else pd.DataFrame()
    column = None
    for candidate in ("cluster", "Cluster"):
        if candidate in df.columns:
            column = candidate
            break
    if column is None:
        return df
    return df[df[column].astype(str).isin(selected)]
