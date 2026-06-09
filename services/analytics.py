"""High-level analytics helpers built on top of the normalizers."""

from __future__ import annotations

from typing import Any

import pandas as pd

from services.normalizers import (
    LEVEL_ORDER,
    build_db_performance_summary,
    normalize_severity,
)


def top_n(df: pd.DataFrame, column: str, n: int = 20, ascending: bool = False) -> pd.DataFrame:
    """Return the top ``n`` rows by ``column`` (numeric)."""

    if df.empty or column not in df.columns:
        return df.head(0)
    table = df.copy()
    table[column] = pd.to_numeric(table[column], errors="coerce")
    table = table.dropna(subset=[column])
    return table.sort_values(column, ascending=ascending).head(n)


def severity_rank(value: Any) -> int:
    """Sort key for severity levels (lower rank = more severe)."""

    return LEVEL_ORDER.get(normalize_severity(value), 99)


def severity_counts(series: pd.Series) -> dict[str, int]:
    """Count rows by normalized severity."""

    if series is None or series.empty:
        return {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "OK": 0}
    normalized = series.map(normalize_severity)
    counts = normalized.value_counts().to_dict()
    return {level: int(counts.get(level, 0)) for level in ["CRITICAL", "WARNING", "INFO", "OK"]}


def db_performance_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Convenience re-export so pages have a single analytics import point."""

    return build_db_performance_summary(df)
