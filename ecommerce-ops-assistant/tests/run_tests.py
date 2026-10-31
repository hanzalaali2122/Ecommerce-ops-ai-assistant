"""
tests/run_tests.py
--------------------------------------------------------------------------
A zero-dependency test runner.

Why this exists: this project's tests (test_metrics.py, test_tools.py)
are written in plain pytest style and will run normally with
`pytest tests/` once you `pip install pytest` (see requirements.txt).
This file exists only because the sandbox this project was first built in
has no internet access, so pytest could not be installed to verify the
work. Rather than skip verification, this script does the minimum pytest
would do: import each test module, find every `test_*` function, run it,
and report pass/fail -- using only the Python standard library.

Run it with:
    python3 tests/run_tests.py
from the project root. Once you have internet access, prefer the real
`pytest tests/ -v` instead -- it gives better output and is the tool the
brief itself asks for ("Testing: pytest and a fixed evaluation dataset").
"""

import importlib
import sys
import os
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_MODULES = ["tests.test_metrics", "tests.test_tools"]


def main():
    total = 0
    failed = 0
    for mod_name in TEST_MODULES:
        module = importlib.import_module(mod_name)
        test_funcs = [getattr(module, name) for name in dir(module)
                      if name.startswith("test_") and callable(getattr(module, name))]
        print(f"\n{mod_name} ({len(test_funcs)} tests)")
        for func in test_funcs:
            total += 1
            try:
                func()
                print(f"  PASS  {func.__name__}")
            except Exception:
                failed += 1
                print(f"  FAIL  {func.__name__}")
                traceback.print_exc()

    print(f"\n{total - failed}/{total} tests passed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
