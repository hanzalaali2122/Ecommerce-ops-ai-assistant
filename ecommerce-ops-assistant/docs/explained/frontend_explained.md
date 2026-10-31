# `frontend/` — explained

**What it is:** a small, dependency-free frontend covering the brief's
three "Application areas" — Chat assistant, Investigation view, Approval
inbox. No build step, no npm, no framework: three plain files
(`index.html`, `style.css`, `app.js`) that `app/main.py` serves
automatically at `/` once this folder has content in it. Styled as a
dark, dashboard-style layout (left sidebar nav, card-based results) using
only a Google Fonts link (Inter + JetBrains Mono) and hand-written CSS —
no UI framework, no CSS framework, no icon library (the nav icons are
inline SVG, hand-written directly in `index.html`).

## Why no framework

The brief's tech stack lists "HTML, CSS, and JavaScript" plainly, and the
actual UI surface needed here is small (a textbox, a results panel, two
tables, some buttons) — not complex enough to justify a build step. Every
request to the API goes through the browser's native `fetch()`.

## Layout: sidebar + content, not top tabs

The sidebar (`<aside class="sidebar">`) holds navigation (Chat/
Investigation/Approvals, each with an inline SVG icon), the role/user-id
fields, and the health badge — all the "who am I, is the server up"
context stays visible no matter which tab you're on. The main area's
header (`#pageTitle` / `#pageSubtitle`) changes per tab (see
`TAB_META` in `app.js`) so the page always explains what you're looking
at, not just what's selected in the nav.

## Example questions pre-fill the input

`EXAMPLES` in `app.js` holds one question per brief workflow, rendered as
clickable cards above the chat box. On page load, the textarea is
pre-filled with the first example's question (`document.getElementById
("question").value = EXAMPLES[0].question`) — so the page is never empty
on first open, and it's obvious at a glance what kind of question the
assistant expects. Clicking any other example card swaps the textarea's
content and focuses it; you still have to click "Ask" yourself, so
nothing fires an API call without an explicit action.

## The revenue-comparison metric strip

When a chat answer's `data` includes a `compare_sales_periods` result
(Workflow A), `renderChatResult` pulls out the headline numbers —
current revenue, previous revenue, the change (amount + percentage), and
the order-count change — into a small row of metric cards, colored green
for an increase and red for a decrease. This sits above the full raw-JSON
dump (`data` is still shown underneath, unabridged) so the reader isn't
forced to parse JSON by eye just to see whether revenue went up or down.

## The three tabs, and which endpoint each one talks to

- **Chat assistant** (`POST /chat`) — a textarea plus a few example
  questions (one per workflow in the brief) that fill it in with one
  click. The response is rendered as: the answer text, any warnings, a
  table of every tool call made (`evidence[]` — tool name, status,
  duration, arguments, and the `result_id` that links back to
  `tool_runs`), any proposed actions awaiting approval, and the raw
  `data` block. The returned `request_id` is auto-filled into the
  Investigation tab's input, so you can switch tabs and immediately pull
  up the full trace for the question you just asked.
- **Investigation view** (`GET /investigations/{request_id}`) — given a
  request ID, renders every row from `tool_runs` for that request as a
  table: when each tool ran, its status (success/error/blocked), timing,
  arguments, and result summary. This is the audit trail the brief asks
  for — nothing in a chat answer should be untraceable back to here.
- **Approval inbox** (`GET /approvals`, plus the approve/reject/execute
  endpoints) — lists every proposed action with its exact payload (not a
  summary — the brief is specific that an approver needs to see the
  exact payload). A `pending` request gets Approve/Reject buttons; an
  `approved` one gets an Execute button. These calls will be rejected by
  the API with a 403 unless the role selector at the top is set to
  `manager` — the UI doesn't hide this restriction, it lets the real 403
  come back so the access-control boundary is visible, not just assumed.

## The role/user picker in the header

Sets the `X-User-Role` / `X-User-Id` headers (`app/auth.py`'s simple
stand-in auth) on every request this page makes. Switching to `analyst`
and trying to approve something is the fastest way to see the
access-control boundary actually enforced, rather than just reading about
it.

## `API_BASE` and how this page finds the server

```js
const API_BASE =
  location.protocol === "http:" || location.protocol === "https:"
    ? location.origin
    : "http://localhost:8000";
```

If this page is served *by* the FastAPI app itself (the normal way — see
below), `location.origin` is already correct, so this just works. If you
instead double-click `index.html` and open it directly as a `file://`
URL, there's no meaningful origin to use, so it falls back to
`http://localhost:8000` — edit this one line if your server runs
somewhere else.

## How to actually see it

```bash
pip install -r requirements.txt
python3 database/build_database.py     # if you haven't already
uvicorn app.main:app --reload --port 8000
```
Then open **http://localhost:8000/** in a browser. `app/main.py`'s last
few lines mount this folder as static files at `/` — after all the API
routes are defined, so API paths like `/chat` and `/approvals` are never
shadowed by the static file server.
