# Final Paper Technical Audit Command Log

All commands ran from `/Users/zhaoxiaoda/Desktop/tbm-bitemporal-twin` on the
`paper-final-technical-audit` branch. No external API or LLM request was made.

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git tag --points-at HEAD

python scripts/audit_final_paper_technical.py

python -m pytest -q tests/unit/test_final_paper_technical_audit.py --cache-clear
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest -q --cache-clear
```

Final results:

- Audit invariants: 9 passed.
- Ruff check: passed.
- Ruff format check: 471 files already formatted.
- Mypy: no issues in 153 source files.
- Full pytest: 687 passed, 5 third-party SWIG deprecation warnings, 117.87 s.
- Frozen hash manifest entries: 441/441 passed.
- Real API calls: 0.
