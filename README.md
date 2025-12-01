# parserAItovar

Utility toolkit for building and testing self-healing product parsers. The
package is dependency-free and includes:

- Heuristic HTML analysis that proposes CSS-like selectors for titles, prices,
  descriptions, images, and attributes.
- Selector self-healing when a page layout changes.
- Lightweight parsing execution using the generated selectors.
- Code generation helpers for Python and Node.js parsers.
- Simple product matching and error-analysis utilities.

## Quick start

```bash
python -m pip install .
pytest
```

See `parserai/core.py` for the available functions.
