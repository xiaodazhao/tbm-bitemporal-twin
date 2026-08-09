from datetime import datetime
from zoneinfo import ZoneInfo

from tbm_twin.metrics.state_metrics import build_state_metric_summaries


def test_state_metric_summary_id_is_independent_of_generated_at() -> None:
    version = {
        "bitemporal_version_id": "b1",
        "base_stage3a_state_version_id": "s1",
        "valid_date": "2023-01-01",
        "knowledge_time_start_local_date": "2023-01-01",
        "version_number": 1,
        "cell_id": "c1",
        "cell_scope_role": "DAILY_REVIEW_CELL",
    }
    rai = {
        "b1": {
            "rai": 0.1,
            "rai_status": "AVAILABLE",
            "dominant_response_family": "LOAD_RESPONSE",
            "reason_codes": [],
            "quality_flags": [],
        }
    }
    grs = {
        "b1": {
            "grs": 0.2,
            "grs_status": "AVAILABLE",
            "available_dimension_count": 1,
            "dimension_coverage_ratio": 1 / 6,
            "dominant_geological_dimension": "EXPLICIT_ANOMALY",
            "observed_support_count": 0,
            "forecast_support_count": 1,
            "reason_codes": [],
            "quality_flags": [],
        }
    }
    grci = {"b1": {"grci": 0.02, "grci_status": "AVAILABLE", "reason_codes": []}}
    first = build_state_metric_summaries(
        [version], rai, grs, grci, datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    second = build_state_metric_summaries(
        [version], rai, grs, grci, datetime(2026, 1, 2, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert first[0]["state_metric_summary_id"] == second[0]["state_metric_summary_id"]
