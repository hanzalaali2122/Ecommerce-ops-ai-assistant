# `tests/test_metrics.py` — explained

**What it is:** unit tests for `metrics.py` — the date-window math and
safe-division helpers every tool depends on. These need no database at
all, which is exactly why they're fast and worth having separately from
`tests/test_tools.py`.

## What each test actually checks, and why it matters

- **`test_last_n_complete_days_excludes_today`** — pins down the
  trickiest date-math rule in the project: "today" is never counted as a
  complete day. Given a fixed "today" of 2026-10-21, "the last 7 complete
  days" must be 2026-10-14 through 2026-10-20 — if this were off by one
  in either direction, every revenue comparison in the project would be
  silently wrong by a day.
- **`test_previous_n_complete_days_is_immediately_before_current`** —
  checks the two windows in a week-over-week comparison butt up against
  each other with no gap and no overlap.
- **`test_date_window_sql_bounds_are_half_open`** — verifies the single
  most bug-prone piece of date math in the project: a window ending
  2026-09-08 must produce a SQL upper bound of `"2026-09-09 00:00:00"`
  (exclusive), not `"2026-09-08 00:00:00"` — otherwise every order placed
  *on* the end date would be silently dropped from every query that uses
  this window.
- **`test_parse_window_rejects_end_before_start`** — a sanity check that
  bad input is rejected with a clear exception, not silently accepted and
  misinterpreted.
- **`test_safe_divide_handles_zero_denominator`** — the brief's "avoid
  division by zero" requirement, tested directly at its source rather
  than only indirectly through whichever tool happens to hit a
  zero-sales edge case.
- **`test_round_money`** — accepts either rounding behavior for the
  classic `1.005` floating-point edge case (banker's rounding vs. normal
  rounding can legitimately differ here across platforms) while still
  checking the common case (`19.999 -> 20.0`) strictly.

## How to run these

```bash
pytest tests/test_metrics.py -v        # once pytest is installed
python3 tests/run_tests.py             # zero-dependency fallback (see that file)
```
