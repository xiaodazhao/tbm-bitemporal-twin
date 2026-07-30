"""PLC reading, normalization, and quality diagnostics."""

from tbm_twin.timeseries.models import (
    NormalizationResult,
    PLCQualityGrade,
    PLCQualityReport,
)
from tbm_twin.timeseries.normalization import normalize_plc_csv, write_normalized_parquet
from tbm_twin.timeseries.quality import evaluate_plc_quality
from tbm_twin.timeseries.reader import read_plc_csv

__all__ = [
    "NormalizationResult",
    "PLCQualityGrade",
    "PLCQualityReport",
    "evaluate_plc_quality",
    "normalize_plc_csv",
    "read_plc_csv",
    "write_normalized_parquet",
]
