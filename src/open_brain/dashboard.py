"""Local dashboard for inspecting and operating the brain."""

from __future__ import annotations

import argparse
import json
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .brain import BrainService
from .observability import log_event


def serve_dashboard(args: argparse.Namespace) -> int:
    server = ThreadingHTTPServer((args.host, args.port), _handler(args.db))
    url = f"http://{args.host}:{args.port}"
    print(f"Brain dashboard listening on {url}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def _handler(db_path: str) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            brain = BrainService(db_path=db_path)
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._html(INDEX_HTML)
                return
            if parsed.path == "/api/stats":
                self._json({"ok": True, "stats": brain.stats()})
                return
            if parsed.path == "/api/events":
                self._json({"ok": True, "events": brain.store.recent_events(limit=100)})
                return
            if parsed.path == "/api/observations":
                self._json({"ok": True, "observations": brain.store.list_observations(limit=150)})
                return
            if parsed.path == "/api/proposals":
                query = parse_qs(parsed.query)
                self._json(
                    {
                        "ok": True,
                        "proposals": brain.list_skill_proposals(
                            status=(query.get("status") or [None])[0], limit=100
                        ),
                    }
                )
                return
            if parsed.path == "/api/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                self._json({"ok": True, "results": brain.recall(query, limit=25)})
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            brain = BrainService(db_path=db_path)
            parsed = urlparse(self.path)
            try:
                body = self._read_json()
                if parsed.path == "/api/ingest":
                    result = brain.ingest(
                        body.get("content", ""),
                        source=body.get("source", "dashboard"),
                        kind=body.get("kind", "note"),
                        workspace=body.get("workspace", "default"),
                        actor=body.get("actor", "dashboard"),
                        metadata=body.get("metadata") or {},
                    )
                    self._json({"ok": True, **result})
                    return
                if parsed.path == "/api/proposals":
                    proposal = brain.propose_skill(
                        body.get("content", ""),
                        title=body.get("title"),
                        target_path=body.get("target_path"),
                        reason=body.get("reason"),
                    )
                    self._json({"ok": True, "proposal": proposal})
                    return
                if parsed.path.startswith("/api/proposals/") and parsed.path.endswith("/apply"):
                    proposal_id = parsed.path.split("/")[3]
                    proposal = brain.apply_skill(
                        proposal_id,
                        allow_root=body["allow_root"],
                        run_tests=body.get("run_tests"),
                    )
                    self._json({"ok": True, "proposal": proposal})
                    return
                if parsed.path.startswith("/api/proposals/") and parsed.path.endswith("/reject"):
                    proposal_id = parsed.path.split("/")[3]
                    proposal = brain.reject_skill(proposal_id, reason=body.get("reason", ""))
                    self._json({"ok": True, "proposal": proposal})
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:  # process boundary: return visible JSON error
                log_event("brain.dashboard.error", error=str(exc), path=parsed.path)
                self._json({"ok": False, "error": exc.__class__.__name__, "message": str(exc)}, 500)

        def _read_json(self) -> dict[str, Any]:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if not raw:
                return {}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                return {}
            return data

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _html(self, html: str) -> None:
            raw = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: Any) -> None:
            log_event("brain.dashboard.http", message=format % args)

    return DashboardHandler


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Open Brain</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #171717;
      --muted: #666f7a;
      --line: #d6d9de;
      --panel: #f7f8fa;
      --accent: #116a67;
      --warn: #8c3f0d;
      --bg: #ffffff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
    }
    h1 { font-size: 20px; margin: 0; letter-spacing: 0; }
    main {
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      min-height: calc(100vh - 62px);
    }
    aside {
      border-right: 1px solid var(--line);
      padding: 18px;
      background: var(--panel);
    }
    section { padding: 20px 24px; }
    label { display: block; font-size: 12px; font-weight: 650; color: var(--muted); margin: 14px 0 6px; }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      background: white;
    }
    textarea { min-height: 108px; resize: vertical; }
    button {
      border: 1px solid var(--accent);
      background: var(--accent);
      color: white;
      border-radius: 6px;
      padding: 9px 12px;
      font-weight: 650;
      cursor: pointer;
    }
    button.secondary { background: white; color: var(--accent); }
    button.warn { border-color: var(--warn); background: var(--warn); }
    .row { display: flex; gap: 8px; align-items: center; }
    .row > * { flex: 1; }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
    .metric { border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
    .metric strong { display: block; font-size: 22px; }
    .tabs { display: flex; gap: 6px; margin: 18px 0; }
    .tabs button { background: white; color: var(--ink); border-color: var(--line); }
    .tabs button.active { border-color: var(--accent); color: var(--accent); }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: #0f1720;
      color: #e8edf2;
      padding: 12px;
      border-radius: 8px;
      max-height: 320px;
      overflow: auto;
    }
    .item { border-top: 1px solid var(--line); padding: 14px 0; }
    .muted { color: var(--muted); }
    .status { min-height: 22px; color: var(--muted); margin-top: 10px; }
    @media (max-width: 850px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <header>
    <h1>Open Brain</h1>
    <div class="muted" id="dbPath"></div>
  </header>
  <main>
    <aside>
      <label for="ingest">Ingest</label>
      <textarea id="ingest" placeholder="Decision: ..."></textarea>
      <div class="row">
        <select id="kind">
          <option>note</option>
          <option>decision</option>
          <option>mistake</option>
          <option>process</option>
        </select>
        <button onclick="ingest()">Save</button>
      </div>
      <label for="skillContent">Skill Proposal</label>
      <textarea id="skillContent" placeholder="Mistake: ..."></textarea>
      <button onclick="propose()">Propose Skill</button>
      <div class="status" id="status"></div>
    </aside>
    <section>
      <div class="stats" id="stats"></div>
      <label for="search">Search</label>
      <div class="row">
        <input id="search" placeholder="workflow handoff, deployment mistake, vendor decision">
        <button onclick="searchBrain()">Search</button>
      </div>
      <div class="tabs">
        <button id="tab-results" class="active" onclick="showTab('results')">Results</button>
        <button id="tab-events" onclick="showTab('events')">Events</button>
        <button id="tab-observations" onclick="showTab('observations')">Observations</button>
        <button id="tab-proposals" onclick="showTab('proposals')">Proposals</button>
      </div>
      <div id="content"></div>
    </section>
  </main>
  <script>
    let active = "results";
    async function api(path, options = {}) {
      const res = await fetch(path, {
        ...options,
        headers: {"Content-Type": "application/json", ...(options.headers || {})}
      });
      return await res.json();
    }
    async function refresh() {
      const stats = await api("/api/stats");
      document.getElementById("dbPath").textContent = stats.stats.db_path;
      document.getElementById("stats").innerHTML = ["events","observations","entities","skill_proposals"]
        .map(k => `<div class="metric"><span class="muted">${k}</span><strong>${stats.stats[k]}</strong></div>`).join("");
      if (active === "events") await loadEvents();
      if (active === "observations") await loadObservations();
      if (active === "proposals") await loadProposals();
    }
    async function ingest() {
      const content = document.getElementById("ingest").value;
      const kind = document.getElementById("kind").value;
      const out = await api("/api/ingest", {method:"POST", body: JSON.stringify({content, kind})});
      document.getElementById("status").textContent = out.ok ? `Saved ${out.event_id}` : out.message;
      await refresh();
    }
    async function propose() {
      const content = document.getElementById("skillContent").value;
      const out = await api("/api/proposals", {method:"POST", body: JSON.stringify({content})});
      document.getElementById("status").textContent = out.ok ? `Proposal ${out.proposal.id}` : out.message;
      showTab("proposals");
    }
    async function searchBrain() {
      const q = encodeURIComponent(document.getElementById("search").value);
      const out = await api(`/api/search?q=${q}`);
      active = "results"; syncTabs();
      renderItems(out.results || []);
    }
    async function loadEvents() {
      const out = await api("/api/events");
      renderItems(out.events || []);
    }
    async function loadObservations() {
      const out = await api("/api/observations");
      renderItems(out.observations || []);
    }
    async function loadProposals() {
      const out = await api("/api/proposals");
      renderProposals(out.proposals || []);
    }
    function showTab(tab) {
      active = tab; syncTabs();
      if (tab === "events") loadEvents();
      if (tab === "observations") loadObservations();
      if (tab === "proposals") loadProposals();
      if (tab === "results") searchBrain();
    }
    function syncTabs() {
      for (const tab of ["results","events","observations","proposals"]) {
        document.getElementById(`tab-${tab}`).classList.toggle("active", tab === active);
      }
    }
    function renderItems(items) {
      document.getElementById("content").innerHTML = items.map(item =>
        `<div class="item"><div><strong>${escapeHtml(item.kind || item.source || "item")}</strong> <span class="muted">${escapeHtml(item.created_at || "")}</span></div><pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre></div>`
      ).join("") || `<div class="muted">No data.</div>`;
    }
    function renderProposals(items) {
      document.getElementById("content").innerHTML = items.map(item =>
        `<div class="item"><div><strong>${escapeHtml(item.title)}</strong> <span class="muted">${escapeHtml(item.status)}</span></div><div class="muted">${escapeHtml(item.target_path)}</div><pre>${escapeHtml(item.patch)}</pre><div class="row"><input id="root-${item.id}" placeholder="Allowed root"><button onclick="applyProposal('${item.id}')">Apply</button><button class="warn" onclick="rejectProposal('${item.id}')">Reject</button></div></div>`
      ).join("") || `<div class="muted">No proposals.</div>`;
    }
    async function applyProposal(id) {
      const allow_root = document.getElementById(`root-${id}`).value;
      const out = await api(`/api/proposals/${id}/apply`, {method:"POST", body: JSON.stringify({allow_root})});
      document.getElementById("status").textContent = out.ok ? `Applied ${id}` : out.message;
      await loadProposals(); await refresh();
    }
    async function rejectProposal(id) {
      const out = await api(`/api/proposals/${id}/reject`, {method:"POST", body: JSON.stringify({reason:"Rejected in dashboard"})});
      document.getElementById("status").textContent = out.ok ? `Rejected ${id}` : out.message;
      await loadProposals(); await refresh();
    }
    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c]));
    }
    refresh(); searchBrain();
  </script>
</body>
</html>
"""
