"""Frozen Stage 2 Parser V2 prototype_text_parser package.

This text-oriented prototype is retained for audit only. Importing this package
does not switch the production raw-geology pipeline. The formal
pdfplumber-backed table parser lives in ``tbm_twin.geology.table_parser_v2``.
"""

from tbm_twin.geology.parsers_v2.registry import parse_pdf_v2, parser_for_source

__all__ = ["parse_pdf_v2", "parser_for_source"]
