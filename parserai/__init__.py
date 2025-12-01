"""Utility toolkit for building self-healing parsers.

This package provides helpers to generate parsing algorithms from HTML,
heal selectors when pages change, and create parser code snippets.
"""

from .core import (
    ParsingAlgorithm,
    ParsingRules,
    analyze_html,
    parse_with_algorithm,
    self_heal_algorithm,
    generate_parser_code,
    match_competitor_product,
    analyze_parser_error,
)

__all__ = [
    "ParsingAlgorithm",
    "ParsingRules",
    "analyze_html",
    "parse_with_algorithm",
    "self_heal_algorithm",
    "generate_parser_code",
    "match_competitor_product",
    "analyze_parser_error",
]
