"""Template signatures consumed by table parser V2."""

from __future__ import annotations

from tbm_twin.geology.table_parser_v2.models import (
    SourceType,
    TemplateSignature,
    TemplateStatus,
)
from tbm_twin.geology.table_parser_v2.pdf_tables import ExtractedPage, ExtractedTable
from tbm_twin.geology.table_parser_v2.text_utils import compact_text


def detect_template_variant(
    source_type: SourceType,
    pages: list[ExtractedPage],
) -> TemplateSignature:
    """Detect a supported template variant from table semantics, not page count alone."""

    tables = [table for page in pages for table in page.tables]
    if source_type == SourceType.FACE_SKETCH:
        return _sketch_variant(tables)
    if source_type == SourceType.SONIC_FORECAST:
        return _hsp_variant(tables)
    if source_type == SourceType.TSP_REPORT:
        return _tsp_variant(tables)
    return TemplateSignature(
        template_variant_id="unsupported_unknown_source",
        source_type=source_type,
        status=TemplateStatus.UNSUPPORTED_TEMPLATE,
        key_headers=(),
        semantic_columns=(),
        table_shape="none",
        continuation_pattern="none",
    )


def _shape_summary(tables: list[ExtractedTable]) -> str:
    return ";".join(
        f"p{table.page_number}:t{table.table_index}:{table.shape[0]}x{table.shape[1]}"
        for table in tables
    )


def _sketch_variant(tables: list[ExtractedTable]) -> TemplateSignature:
    main_tables = [
        table
        for table in tables
        if all(token in compact_text(table.joined_text()) for token in ["掌子面状态", "地质描述"])
    ]
    if not main_tables:
        return TemplateSignature(
            template_variant_id="sketch_unsupported_no_main_table",
            source_type=SourceType.FACE_SKETCH,
            status=TemplateStatus.UNSUPPORTED_TEMPLATE,
            key_headers=("洞身段地质素描记录表",),
            semantic_columns=(),
            table_shape=_shape_summary(tables),
            continuation_pattern="no_main_table",
        )
    table = main_tables[0]
    item_tokens = ["掌子面尺寸", "掌子面状态", "毛开挖面状态", "风化程度", "地质描述"]
    return TemplateSignature(
        template_variant_id=f"sketch_main_table_{table.shape[0]}x{table.shape[1]}",
        source_type=SourceType.FACE_SKETCH,
        status=TemplateStatus.SUPPORTED,
        key_headers=("编号", "项目名称", "状态描述"),
        semantic_columns=tuple(item_tokens),
        table_shape=_shape_summary([table]),
        continuation_pattern="single_main_table_with_possible_description_continuation",
    )


def _hsp_variant(tables: list[ExtractedTable]) -> TemplateSignature:
    header_tables = [
        table
        for table in tables
        if all(token in compact_text(table.joined_text()) for token in ["里程范围", "本次预报结论"])
    ]
    if not header_tables:
        return TemplateSignature(
            template_variant_id="hsp_unsupported_no_forecast_table",
            source_type=SourceType.SONIC_FORECAST,
            status=TemplateStatus.UNSUPPORTED_TEMPLATE,
            key_headers=("里程范围", "本次预报结论"),
            semantic_columns=(),
            table_shape=_shape_summary(tables),
            continuation_pattern="no_forecast_table",
        )
    shapes = {
        table.shape[1]
        for table in tables
        if "DyK" in table.joined_text() or "Dyk" in table.joined_text()
    }
    continuation = (
        "continued_without_repeated_header" if any(cols < 7 for cols in shapes) else "single_table"
    )
    return TemplateSignature(
        template_variant_id=f"hsp_forecast_{continuation}",
        source_type=SourceType.SONIC_FORECAST,
        status=TemplateStatus.SUPPORTED,
        key_headers=("里程范围", "物探探测结果", "预报结论", "风险提示", "建议围岩等级"),
        semantic_columns=(
            "range",
            "geophysical_result",
            "geological_conclusion",
            "risk_hint",
            "suggested_grade",
        ),
        table_shape=_shape_summary(tables),
        continuation_pattern=continuation,
    )


def _tsp_variant(tables: list[ExtractedTable]) -> TemplateSignature:
    header_tables = [
        table
        for table in tables
        if all(
            token in compact_text(table.joined_text())
            for token in ["里程范围", "物性参数", "预报结论"]
        )
    ]
    if not header_tables:
        return TemplateSignature(
            template_variant_id="tsp_unsupported_no_forecast_table",
            source_type=SourceType.TSP_REPORT,
            status=TemplateStatus.UNSUPPORTED_TEMPLATE,
            key_headers=("里程范围", "物性参数", "预报结论"),
            semantic_columns=(),
            table_shape=_shape_summary(tables),
            continuation_pattern="no_forecast_table",
        )
    shapes = {
        table.shape[1]
        for table in tables
        if "DyK" in table.joined_text() or "Dyk" in table.joined_text()
    }
    continuation = "mixed_6col_4col_continuation" if len(shapes) > 1 else "single_shape"
    return TemplateSignature(
        template_variant_id=f"tsp_table2_{continuation}",
        source_type=SourceType.TSP_REPORT,
        status=TemplateStatus.SUPPORTED,
        key_headers=("里程范围", "物性参数", "物探分析", "预报结论"),
        semantic_columns=(
            "range",
            "physical_parameters",
            "physical_interpretation",
            "geological_conclusion",
        ),
        table_shape=_shape_summary(tables),
        continuation_pattern=continuation,
    )
