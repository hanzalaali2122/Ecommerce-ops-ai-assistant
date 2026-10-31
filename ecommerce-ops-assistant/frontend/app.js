// frontend/app.js
// --------------------------------------------------------------------------
// A small, dependency-free frontend for the three "Application areas" the
// project brief describes: Chat assistant, Investigation view, Approval
// inbox. No build step -- just open index.html through the FastAPI server
// (uvicorn app.main:app serves this whole folder at "/") or any static
// file server, and it talks to the API with plain fetch() calls.
//
// If you open this file directly (double-click index.html) instead of
// through uvicorn, API_BASE falls back to http://localhost:8000 -- make
// sure that's where your server is actually running, or edit API_BASE
// below.

const API_BASE =
  location.protocol === "http:" || location.protocol === "https:"
    ? location.origin
    : "http://localhost:8000";

document.getElementById("apiBaseLabel").textContent = API_BASE;

// ---------------------------------------------------------------------------
// Example questions -- one per brief workflow. Shown as cards on the chat
// tab, and the first one pre-fills the textarea on load so the page never
// looks empty / makes it obvious what kind of thing to ask.
// ---------------------------------------------------------------------------

const EXAMPLES = [
  {
    label: "Workflow A — sales decline",
    question:
      "Compare the last seven complete days with the previous seven. What drove the revenue change?",
  },
  {
    label: "Workflow B — replenishment",
    question:
      "Which products may run out within two weeks, and how much should we reorder?",
  },
  {
    label: "Workflow C — order lookup",
    question: "Check order 536365. What was purchased, and is it refunded?",
  },
  {
    label: "Workflow D — discount proposal",
    question:
      "Prepare a 10 percent discount for slow-selling jackets for three days.",
  },
];

const SEARCH_ICON =
  '<svg viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="1.8"/><path d="m21 21-4.35-4.35" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function currentRole() {
  return document.getElementById("role").value;
}
function currentUser() {
  return document.getElementById("userId").value || "demo-user";
}

async function apiFetch(path, options = {}) {
  const headers = Object.assign(
    {
      "Content-Type": "application/json",
      "X-User-Role": currentRole(),
      "X-User-Id": currentUser(),
    },
    options.headers || {}
  );
  const res = await fetch(API_BASE + path, { ...options, headers });
  let body;
  try {
    body = await res.json();
  } catch {
    body = { error: "invalid_response", message: `HTTP ${res.status}` };
  }
  if (!res.ok) {
    const message = body && body.detail ? body.detail : JSON.stringify(body);
    throw new Error(`HTTP ${res.status}: ${message}`);
  }
  return body;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  }
  for (const child of [].concat(children)) {
    if (child) node.appendChild(child);
  }
  return node;
}

function card(titleText, bodyNode) {
  return el("div", { class: "card" }, [el("h3", { text: titleText }), bodyNode]);
}

function pretty(obj) {
  return el("pre", { text: JSON.stringify(obj, null, 2) });
}

function fmtMoney(n) {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(n);
}
function fmtPct(n) {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Example cards
// ---------------------------------------------------------------------------

function renderExamples() {
  const grid = document.getElementById("examplesGrid");
  grid.innerHTML = "";
  EXAMPLES.forEach((ex) => {
    const btn = el("button", { class: "example-card", type: "button" }, [
      el("div", { class: "eyebrow", html: `${SEARCH_ICON}<span>${ex.label}</span>` }),
      el("p", { text: ex.question }),
    ]);
    btn.addEventListener("click", () => {
      const ta = document.getElementById("question");
      ta.value = ex.question;
      ta.focus();
    });
    grid.appendChild(btn);
  });
}
renderExamples();

// Pre-fill the textarea with the first example so the chat tab never opens
// empty -- makes it obvious at a glance what kind of question this expects.
document.getElementById("question").value = EXAMPLES[0].question;

// ---------------------------------------------------------------------------
// Tabs (also update the page header per tab)
// ---------------------------------------------------------------------------

const TAB_META = {
  chat: {
    title: "Chat assistant",
    subtitle: "Ask a business question in plain English — every answer is backed by real tool calls, never guessed.",
  },
  investigation: {
    title: "Investigation view",
    subtitle: "Every tool call behind one answer: arguments, status, timing, and the exact result returned.",
  },
  approvals: {
    title: "Approval inbox",
    subtitle: "Discounts and inventory-alert changes proposed by the assistant wait here until a manager approves them.",
  },
};

function activateTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  const meta = TAB_META[name];
  if (meta) {
    document.getElementById("pageTitle").textContent = meta.title;
    document.getElementById("pageSubtitle").textContent = meta.subtitle;
  }
  if (name === "approvals") loadApprovals();
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

// ---------------------------------------------------------------------------
// Health badge + pending-approvals badge
// ---------------------------------------------------------------------------

async function checkHealth() {
  const badge = document.getElementById("healthBadge");
  try {
    const h = await apiFetch("/health");
    badge.textContent = `${h.agent_mode} mode · db ${h.database_ready ? "ready" : "missing"}`;
    badge.className = "health-badge ok";
  } catch (err) {
    badge.textContent = "API unreachable";
    badge.className = "health-badge err";
  }
}
checkHealth();

async function refreshPendingBadge() {
  const badge = document.getElementById("pendingBadge");
  try {
    const list = await apiFetch("/approvals?status=pending");
    if (list.length > 0) {
      badge.textContent = list.length;
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
  } catch {
    badge.hidden = true;
  }
}
refreshPendingBadge();

// ---------------------------------------------------------------------------
// Chat assistant
// ---------------------------------------------------------------------------

document.getElementById("chatForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = document.getElementById("question").value.trim();
  const resultBox = document.getElementById("chatResult");
  if (!question) return;

  resultBox.innerHTML = "";
  resultBox.appendChild(card("Status", el("p", { class: "muted", text: "Asking…" })));

  try {
    const res = await apiFetch("/chat", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    renderChatResult(res);
    if (res.request_id) {
      document.getElementById("requestId").value = res.request_id;
    }
    refreshPendingBadge();
  } catch (err) {
    resultBox.innerHTML = "";
    resultBox.appendChild(card("Error", el("p", { class: "warning", text: err.message })));
  }
});

function renderChatResult(res) {
  const box = document.getElementById("chatResult");
  box.innerHTML = "";

  box.appendChild(card("Answer", el("div", { class: "answer", text: res.answer || "(no answer text)" })));

  // A small headline-metrics strip, specifically when a compare_sales_periods
  // result is present (Workflow A) -- turns the key numbers into something
  // scannable instead of making the reader dig through raw JSON for them.
  const cmp = res.data && (res.data.compare_sales_periods || res.data["compare_sales_periods_1"]);
  if (cmp) {
    const changeUp = cmp.revenue_change >= 0;
    const metrics = el("div", { class: "metric-row" }, [
      metric("Current revenue", fmtMoney(cmp.current?.revenue)),
      metric("Previous revenue", fmtMoney(cmp.previous?.revenue)),
      metric("Change", `${changeUp ? "+" : ""}${fmtMoney(cmp.revenue_change)} (${fmtPct(cmp.revenue_change_pct)})`, changeUp ? "up" : "down"),
      metric("Order count change", `${cmp.order_count_change >= 0 ? "+" : ""}${cmp.order_count_change}`, cmp.order_count_change >= 0 ? "up" : "down"),
    ]);
    box.appendChild(card("Revenue comparison", metrics));
  }

  if (res.warnings && res.warnings.length) {
    const list = el("ul");
    res.warnings.forEach((w) => list.appendChild(el("li", { class: "warning", text: w })));
    box.appendChild(card("Warnings", list));
  }

  if (res.evidence && res.evidence.length) {
    const table = el("table");
    table.appendChild(
      el("tr", {}, [
        el("th", { text: "Tool" }),
        el("th", { text: "Status" }),
        el("th", { text: "Duration" }),
        el("th", { text: "Arguments" }),
        el("th", { text: "Result ID" }),
      ])
    );
    res.evidence.forEach((e) => {
      table.appendChild(
        el("tr", {}, [
          el("td", { text: e.tool }),
          el("td", {}, el("span", { class: `pill ${e.status}`, text: e.status })),
          el("td", { text: `${e.duration_ms} ms` }),
          el("td", {}, pretty(e.arguments)),
          el("td", { class: "mono", text: (e.result_id || "").slice(0, 8) }),
        ])
      );
    });
    box.appendChild(card(`Evidence (${res.evidence.length} tool call${res.evidence.length === 1 ? "" : "s"})`, table));
  }

  if (res.proposed_actions && res.proposed_actions.length) {
    box.appendChild(
      card(
        "Proposed actions (pending human approval)",
        el("div", {}, [
          el("p", { class: "muted", text: "Not live yet — review and approve these in the Approval inbox tab." }),
          pretty(res.proposed_actions),
        ])
      )
    );
  }

  if (res.data && Object.keys(res.data).length) {
    box.appendChild(card("Raw tool data", pretty(res.data)));
  }

  box.appendChild(
    card(
      "Request ID",
      el("p", { class: "muted", html: `<code>${res.request_id}</code> — see the Investigation view tab for the full trace.` })
    )
  );
}

function metric(label, value, trend) {
  return el("div", { class: "metric" }, [
    el("div", { class: "label", text: label }),
    el("div", { class: `value ${trend || ""}`, text: value }),
  ]);
}

// ---------------------------------------------------------------------------
// Investigation view
// ---------------------------------------------------------------------------

document.getElementById("investigationForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const requestId = document.getElementById("requestId").value.trim();
  const box = document.getElementById("investigationResult");
  if (!requestId) return;

  box.innerHTML = "";
  try {
    const res = await apiFetch(`/investigations/${encodeURIComponent(requestId)}`);
    const table = el("table");
    table.appendChild(
      el("tr", {}, [
        el("th", { text: "Started" }),
        el("th", { text: "Tool" }),
        el("th", { text: "Status" }),
        el("th", { text: "Duration" }),
        el("th", { text: "Arguments" }),
        el("th", { text: "Result summary" }),
      ])
    );
    res.tool_runs.forEach((r) => {
      table.appendChild(
        el("tr", {}, [
          el("td", { class: "mono", text: r.started_at }),
          el("td", { text: r.tool_name }),
          el("td", {}, el("span", { class: `pill ${r.status}`, text: r.status })),
          el("td", { text: `${r.duration_ms} ms` }),
          el("td", {}, pretty(JSON.parse(r.arguments))),
          el("td", {}, pretty(r.result_summary ? JSON.parse(r.result_summary) : null)),
        ])
      );
    });
    box.appendChild(card(`Tool runs for ${requestId}`, table));
  } catch (err) {
    box.appendChild(card("Error", el("p", { class: "warning", text: err.message })));
  }
});

// ---------------------------------------------------------------------------
// Approval inbox
// ---------------------------------------------------------------------------

async function loadApprovals() {
  const box = document.getElementById("approvalsResult");
  const status = document.getElementById("approvalStatus").value;
  box.innerHTML = "";
  try {
    const qs = status ? `?status=${encodeURIComponent(status)}` : "";
    const list = await apiFetch(`/approvals${qs}`);
    if (!list.length) {
      box.appendChild(card("Approval requests", el("p", { class: "muted", text: "Nothing here." })));
      return;
    }
    list.forEach((req) => box.appendChild(renderApprovalCard(req)));
  } catch (err) {
    box.appendChild(card("Error", el("p", { class: "warning", text: err.message })));
  }
}

function renderApprovalCard(req) {
  const head = el("div", { class: "card-head" }, [
    el("span", { class: `pill ${req.status}`, text: req.status }),
    el("strong", { text: req.action }),
    el("span", { class: "muted", text: `by ${req.requester} · ${req.created_at}` }),
  ]);
  const body = el("div", {}, [head, pretty(req.payload)]);

  if (req.status === "pending") {
    const actions = el("div", { class: "approval-actions" });
    const approveBtn = el("button", { class: "approve", text: "Approve" });
    const rejectBtn = el("button", { class: "reject", text: "Reject" });
    approveBtn.addEventListener("click", () => decideApproval(req.request_id, "approve"));
    rejectBtn.addEventListener("click", () => decideApproval(req.request_id, "reject"));
    actions.appendChild(approveBtn);
    actions.appendChild(rejectBtn);
    body.appendChild(actions);
    body.appendChild(el("p", { class: "muted", text: "Approving/rejecting requires the 'manager' role (set in the sidebar)." }));
  } else if (req.status === "approved") {
    const actions = el("div", { class: "approval-actions" });
    const executeBtn = el("button", { class: "execute", text: "Execute" });
    executeBtn.addEventListener("click", () => executeApproval(req.request_id));
    actions.appendChild(executeBtn);
    body.appendChild(actions);
  }

  return card(req.request_id, body);
}

async function decideApproval(requestId, action) {
  try {
    await apiFetch(`/approvals/${encodeURIComponent(requestId)}/${action}`, { method: "POST" });
    await loadApprovals();
    refreshPendingBadge();
  } catch (err) {
    alert(err.message);
  }
}

async function executeApproval(requestId) {
  try {
    await apiFetch(`/approvals/${encodeURIComponent(requestId)}/execute`, { method: "POST" });
    await loadApprovals();
  } catch (err) {
    alert(err.message);
  }
}

document.getElementById("refreshApprovals").addEventListener("click", (e) => {
  e.preventDefault();
  loadApprovals();
});
document.getElementById("approvalStatus").addEventListener("change", loadApprovals);
