import json
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from parserai.core import (
    ParsingAlgorithm,
    ParsingRules,
    analyze_html,
    analyze_parser_error,
    generate_parser_code,
    match_competitor_product,
    parse_with_algorithm,
    self_heal_algorithm,
)


SAMPLE_HTML = """
<html>
  <body>
    <h1 class="product-title">Sample Product</h1>
    <div class="price">$10.00</div>
    <div class="product-description">This is a description.</div>
    <div class="gallery">
        <img src="/img/1.jpg" />
    </div>
    <ul class="spec-list">
        <li>Feature A</li>
    </ul>
  </body>
</html>
"""


def test_analyze_and_parse_cycle():
    algo = analyze_html(SAMPLE_HTML)
    data = parse_with_algorithm(SAMPLE_HTML, algo)
    assert "Sample Product" in data["title"]
    assert "10" in data["price"]
    assert "description" in data["description"]
    assert data["images"]
    assert data["attributes"]


def test_self_heal_updates_missing_selector():
    algo = analyze_html(SAMPLE_HTML)
    broken = ParsingAlgorithm(selectors={k: "#missing" for k in algo.selectors}, rules=ParsingRules(), meta={"confidence": 0.5, "warnings": []})
    healed = self_heal_algorithm(SAMPLE_HTML, broken)
    assert healed.selectors["title"] != "#missing"


def test_generate_parser_code_variants():
    algo = analyze_html(SAMPLE_HTML)
    py_code = generate_parser_code(algo, "python")
    node_code = generate_parser_code(algo, "node")
    assert "def parse" in py_code
    assert "async function parse" in node_code


def test_matching_returns_confidence():
    catalog = {1: "Sample Product", 2: "Another"}
    result = match_competitor_product("Sample Product XL", catalog)
    assert result["our_id"] == 1
    assert result["match_confidence"] > 0


def test_error_analysis_flags_timeout():
    snippet = "print('hi')"
    result = analyze_parser_error("Timeout while fetching", snippet)
    assert result["error_reason"] == "request timed out"
    assert "increase timeout" in result["fixed_code"]


if __name__ == "__main__":
    print(json.dumps({
        "analyze": analyze_html(SAMPLE_HTML).to_json(),
        "parsed": parse_with_algorithm(SAMPLE_HTML, analyze_html(SAMPLE_HTML)),
    }, indent=2))
