# `tools/external.py` — explained

**What it is:** the one tool in the entire project that calls something
outside the database — a (normally) live exchange-rate API. Small file,
but it demonstrates an important principle: **never invent a number you
couldn't actually get.**

## `get_exchange_rate(base_currency, target_currency)`

1. Validates both currency codes against a small allowlist
   (`tools/validation.py`'s `validate_currency`).
2. If `base == target`, short-circuits to `rate: 1.0` with
   `source: "identity"` — no need to call out to the network for "GBP to
   GBP".
3. Otherwise, really attempts a live HTTP call to an exchange-rate API,
   with a 5-second timeout.
4. **If that call succeeds**, returns the real rate with
   `source: "live_api"`.
5. **If it fails for any reason** — network unreachable, timeout, bad
   response — it returns an explicit `available: false` result with
   `rate: None` and a plain-English explanation, instead of fabricating a
   plausible-looking number.

## Why step 5 matters so much

The brief's own evaluation table has a test case built specifically for
this: *"External API timeout → Explain unavailable conversion; invent no
rate."* An AI model under pressure to "just answer the question" might
be tempted to guess a reasonable-sounding exchange rate if the tool
silently returned nothing. By having the tool itself return a clearly
structured "this failed, here's why, don't pretend it didn't" result, the
model has something honest to relay instead of a gap it might paper over.

This project's own sandbox has no outbound internet access to that
exchange-rate API, so in practice this function will exercise the
*failure* path every time it's actually run here — which is itself a
live demonstration that the failure handling works, not a bug to fix.

## What this tool deliberately does NOT do

It never touches any stored revenue or margin figure. Per
`metrics.py`'s currency policy, all stored amounts stay in GBP always; a
fetched exchange rate is a point-in-time reference for *display* only
("what would that be in USD right now"), never something that recomputes
history.

## How this connects to the rest of the project

Registered in `tools/schemas.py` at the lowest (`analyst`) role tier,
since it exposes no sensitive data — it's a pure utility lookup.
