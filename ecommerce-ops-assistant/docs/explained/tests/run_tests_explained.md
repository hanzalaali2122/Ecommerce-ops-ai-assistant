# `tests/run_tests.py` — explained

**What it is:** a zero-dependency test runner — the fallback used when
`pytest` isn't installed (e.g. this project's own sandbox had no
outbound internet access to `pip install` anything at all, even over the
allowlisted package-registry proxy, when this project was built and
verified).

## What it does

```python
TEST_MODULES = ["tests.test_metrics", "tests.test_tools"]
```

For each test module: imports it, finds every function whose name starts
with `test_`, calls it, and reports PASS or FAIL with a full traceback on
failure. No fixtures, no parametrization, no assertion-rewriting — just
"import, call, catch exceptions" — the minimum pytest itself would do for
tests written in this plain `def test_x(): assert ...` style (which is
why these same test files also run unmodified under real pytest, once
it's available).

## Why this is only a fallback, not the "real" way to run tests

The project brief's own tech stack explicitly names `pytest` as the
testing tool. This runner exists purely so test coverage could be
verified at all in a no-internet environment, not as a replacement for
pytest's much better output (clear diffs on assertion failures,
fixtures, parametrized tests, parallel runs, plugins). Prefer:

```bash
pip install pytest   # or pip install -r requirements.txt
pytest tests/ -v
```

whenever you have the ability to install it. This script stays in the
project as a safety net for environments that can't.

## Usage

```bash
python3 tests/run_tests.py
```
from the project root. Exits with status code 1 if anything failed (so
it can be used in a CI step even without pytest available).
