from __future__ import annotations

import argparse
import json
import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .forum import Forum
from .issue import Issue
from .util import utc_now_iso

_SESSION_TOPIC_RE = re.compile(r"^(?P<prefix>loopfarm):session:(?P<session_id>[^\s]+)$")
_MESSAGE_SUMMARY_MAX = 220

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>loopfarm monitor</title>
  <style>
    :root {
      --bg: #0d0f11;
      --panel: #14181d;
      --panel-2: #1b2026;
      --fg: #dde4ea;
      --muted: #8d9aa8;
      --ok: #57d68d;
      --warn: #f8cd6e;
      --err: #ff7f7f;
      --accent: #6ee7f7;
      --border: #2a333d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #0b0d10 0%, var(--bg) 100%);
      color: var(--fg);
      font-family: "JetBrains Mono", "Iosevka Term", "IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.35;
    }
    .top {
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(13, 15, 17, 0.96);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid var(--border);
      padding: 8px 10px;
      display: grid;
      gap: 6px;
    }
    .brand { color: var(--accent); font-weight: 700; }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 6px;
    }
    .metric {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 4px 6px;
      min-height: 40px;
    }
    .metric .k { color: var(--muted); font-size: 11px; }
    .metric .v { font-size: 14px; font-weight: 700; }
    .filter-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
    }
    .filter-row input {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel);
      color: var(--fg);
      padding: 6px 8px;
      font: inherit;
    }
    .container {
      display: grid;
      gap: 8px;
      padding: 8px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }
    .panel h2 {
      margin: 0;
      padding: 8px 10px;
      background: var(--panel-2);
      border-bottom: 1px solid var(--border);
      font-size: 12px;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }
    .scroll {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      white-space: nowrap;
    }
    th, td {
      text-align: left;
      border-bottom: 1px solid var(--border);
      padding: 6px 8px;
      vertical-align: top;
    }
    th { color: var(--muted); font-weight: 600; }
    tr:hover { background: rgba(255, 255, 255, 0.03); cursor: pointer; }
    .status-running { color: var(--ok); }
    .status-complete { color: var(--accent); }
    .status-interrupted, .status-stopped { color: var(--warn); }
    .status-failed, .status-error { color: var(--err); }
    .mono-pre {
      margin: 0;
      padding: 8px;
      max-height: 280px;
      overflow: auto;
      background: #0f1318;
      border-top: 1px solid var(--border);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .hint { color: var(--muted); padding: 8px; }
    .topic-msg {
      border-top: 1px solid var(--border);
      padding: 6px 8px;
    }
    .topic-msg .meta { color: var(--muted); }
    .topic-msg .body { margin-top: 2px; white-space: pre-wrap; word-break: break-word; }
    @media (min-width: 980px) {
      .container {
        grid-template-columns: 1.2fr 1fr;
        grid-template-areas:
          "loops details"
          "issues forum";
      }
      #panel-loops { grid-area: loops; }
      #panel-details { grid-area: details; }
      #panel-issues { grid-area: issues; }
      #panel-forum { grid-area: forum; }
    }
  </style>
</head>
<body>
  <header class="top">
    <div><span class="brand">loopfarm monitor</span> <span id="generated" class="hint"></span></div>
    <div class="metrics">
      <div class="metric"><div class="k">Active Loops</div><div id="m-active" class="v">-</div></div>
      <div class="metric"><div class="k">In Progress Issues</div><div id="m-inprogress" class="v">-</div></div>
      <div class="metric"><div class="k">Open Issues</div><div id="m-open" class="v">-</div></div>
      <div class="metric"><div class="k">Forum Topics</div><div id="m-topics" class="v">-</div></div>
    </div>
    <div class="filter-row">
      <input id="filter" type="text" placeholder="filter sessions/issues/topics (id, title, prompt, tag)" />
      <span id="host" class="hint"></span>
    </div>
  </header>

  <main class="container">
    <section id="panel-loops" class="panel">
      <h2>Loops</h2>
      <div class="scroll">
        <table>
          <thead>
            <tr><th>Session</th><th>Status</th><th>Phase</th><th>Iter</th><th>Started</th><th>Prompt</th></tr>
          </thead>
          <tbody id="sessions-body"></tbody>
        </table>
      </div>
    </section>

    <section id="panel-details" class="panel">
      <h2>Details</h2>
      <div id="details-empty" class="hint">Tap a session or forum topic for details.</div>
      <pre id="details-pre" class="mono-pre" style="display:none"></pre>
      <div id="topic-messages"></div>
    </section>

    <section id="panel-issues" class="panel">
      <h2>Issues</h2>
      <div class="scroll">
        <table>
          <thead>
            <tr><th>ID</th><th>St</th><th>P</th><th>Updated</th><th>Title</th></tr>
          </thead>
          <tbody id="issues-body"></tbody>
        </table>
      </div>
    </section>

    <section id="panel-forum" class="panel">
      <h2>Forum Topics</h2>
      <div class="scroll">
        <table>
          <thead>
            <tr><th>Topic</th><th>Type</th><th>Created</th></tr>
          </thead>
          <tbody id="topics-body"></tbody>
        </table>
      </div>
    </section>
  </main>

  <script>
    const REFRESH_MS = __REFRESH_MS__;
    const state = {
      data: null,
      filter: "",
      selectedSession: null,
      selectedTopic: null,
    };

    function esc(v) {
      return String(v ?? "").replace(/[&<>\"]/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[ch]));
    }

    function fmtTime(value) {
      if (!value) return "-";
      const d = new Date(value);
      if (Number.isNaN(d.valueOf())) return String(value);
      return d.toLocaleString([], { hour12: false });
    }

    function isMatch(text) {
      if (!state.filter) return true;
      return String(text || "").toLowerCase().includes(state.filter);
    }

    function applyMetrics(data) {
      const counts = data.issue_counts || {};
      document.getElementById("generated").textContent = `updated ${fmtTime(data.generated_at)}`;
      document.getElementById("host").textContent = `${data.host || "-"} · refresh ${Math.round(REFRESH_MS / 1000)}s`;
      document.getElementById("m-active").textContent = String((data.sessions || []).filter((s) => s.status === "running").length);
      document.getElementById("m-inprogress").textContent = String(counts.in_progress || 0);
      document.getElementById("m-open").textContent = String(counts.open || 0);
      document.getElementById("m-topics").textContent = String((data.forum_topics || []).length);
    }

    function renderSessions(data) {
      const rows = (data.sessions || []).filter((s) => {
        const hay = `${s.session_id} ${s.status} ${s.phase || ""} ${s.prompt || ""}`;
        return isMatch(hay);
      });
      const html = rows.map((s) => {
        const statusClass = `status-${String(s.status || "").toLowerCase()}`;
        return `<tr data-kind="session" data-id="${esc(s.session_id)}">`
          + `<td>${esc(s.session_id)}</td>`
          + `<td class="${statusClass}">${esc(s.status || "-")}</td>`
          + `<td>${esc(s.phase || "-")}</td>`
          + `<td>${esc(s.iteration ?? "-")}</td>`
          + `<td>${esc(fmtTime(s.started))}</td>`
          + `<td>${esc(s.prompt || "")}</td>`
          + `</tr>`;
      }).join("");
      document.getElementById("sessions-body").innerHTML = html || `<tr><td colspan="6" class="hint">No matching sessions.</td></tr>`;
    }

    function renderIssues(data) {
      const rows = (data.issues || []).filter((i) => {
        const hay = `${i.id} ${i.status} ${i.title} ${i.tags || ""}`;
        return isMatch(hay);
      });
      const html = rows.map((i) => {
        return `<tr>`
          + `<td>${esc(i.id)}</td>`
          + `<td>${esc(i.status)}</td>`
          + `<td>${esc(i.priority ?? "-")}</td>`
          + `<td>${esc(fmtTime(i.updated_at_iso || i.updated_at))}</td>`
          + `<td>${esc(i.title)}</td>`
          + `</tr>`;
      }).join("");
      document.getElementById("issues-body").innerHTML = html || `<tr><td colspan="5" class="hint">No matching issues.</td></tr>`;
    }

    function renderTopics(data) {
      const rows = (data.forum_topics || []).filter((t) => isMatch(`${t.name} ${t.kind}`));
      const html = rows.map((t) => {
        return `<tr data-kind="topic" data-name="${esc(t.name)}">`
          + `<td>${esc(t.name)}</td>`
          + `<td>${esc(t.kind)}</td>`
          + `<td>${esc(fmtTime(t.created_at_iso || t.created_at))}</td>`
          + `</tr>`;
      }).join("");
      document.getElementById("topics-body").innerHTML = html || `<tr><td colspan="3" class="hint">No matching topics.</td></tr>`;
    }

    function renderSessionDetail(sessionId) {
      const detailsPre = document.getElementById("details-pre");
      const detailsEmpty = document.getElementById("details-empty");
      const topicMessages = document.getElementById("topic-messages");
      topicMessages.innerHTML = "";
      const session = (state.data.sessions || []).find((s) => s.session_id === sessionId);
      if (!session) {
        detailsEmpty.style.display = "block";
        detailsPre.style.display = "none";
        return;
      }
      const lines = [];
      lines.push(`session:   ${session.session_id}`);
      lines.push(`topic:     ${session.topic}`);
      lines.push(`status:    ${session.status || "-"}`);
      lines.push(`phase:     ${session.phase || "-"}`);
      lines.push(`iteration: ${session.iteration ?? "-"}`);
      lines.push(`started:   ${fmtTime(session.started)}`);
      lines.push(`ended:     ${fmtTime(session.ended)}`);
      lines.push(`decision:  ${session.decision || "-"}`);
      lines.push("");
      lines.push("prompt:");
      lines.push(session.prompt || "");
      lines.push("");
      lines.push("latest summary:");
      lines.push(session.latest_summary || "-");
      lines.push("");
      lines.push("recent phase summaries:");
      for (const b of (session.briefings || [])) {
        lines.push(`- [${b.phase || "?"} #${b.iteration ?? "?"}] ${b.summary || ""}`);
      }
      detailsPre.textContent = lines.join("\n");
      detailsEmpty.style.display = "none";
      detailsPre.style.display = "block";
    }

    async function renderTopicDetail(topicName) {
      const detailsPre = document.getElementById("details-pre");
      const detailsEmpty = document.getElementById("details-empty");
      const topicMessages = document.getElementById("topic-messages");
      detailsPre.style.display = "none";
      detailsEmpty.style.display = "none";
      topicMessages.innerHTML = `<div class="hint">loading ${esc(topicName)}...</div>`;
      try {
        const resp = await fetch(`/api/topic?name=${encodeURIComponent(topicName)}&limit=20`, { cache: "no-store" });
        if (!resp.ok) throw new Error(`status ${resp.status}`);
        const data = await resp.json();
        const lines = [`topic: ${topicName}`, `messages: ${(data.messages || []).length}`];
        detailsPre.textContent = lines.join("\n");
        detailsPre.style.display = "block";
        topicMessages.innerHTML = (data.messages || []).map((m) => {
          return `<div class="topic-msg">`
            + `<div class="meta">${esc(fmtTime(m.created_at_iso || m.created_at))} · ${esc(m.id || "-")}</div>`
            + `<div class="body">${esc(m.summary || "")}</div>`
            + `</div>`;
        }).join("") || `<div class="hint">No messages.</div>`;
      } catch (err) {
        topicMessages.innerHTML = `<div class="hint">failed to load topic: ${esc(err.message || err)}</div>`;
      }
    }

    function attachHandlers() {
      document.getElementById("filter").addEventListener("input", (ev) => {
        state.filter = String(ev.target.value || "").trim().toLowerCase();
        if (state.data) {
          renderSessions(state.data);
          renderIssues(state.data);
          renderTopics(state.data);
        }
      });

      document.getElementById("sessions-body").addEventListener("click", (ev) => {
        const row = ev.target.closest("tr[data-kind='session']");
        if (!row) return;
        state.selectedSession = row.getAttribute("data-id");
        state.selectedTopic = null;
        renderSessionDetail(state.selectedSession);
      });

      document.getElementById("topics-body").addEventListener("click", (ev) => {
        const row = ev.target.closest("tr[data-kind='topic']");
        if (!row) return;
        state.selectedTopic = row.getAttribute("data-name");
        state.selectedSession = null;
        renderTopicDetail(state.selectedTopic);
      });
    }

    async function tick() {
      try {
        const resp = await fetch("/api/overview", { cache: "no-store" });
        if (!resp.ok) throw new Error(`status ${resp.status}`);
        const data = await resp.json();
        state.data = data;
        applyMetrics(data);
        renderSessions(data);
        renderIssues(data);
        renderTopics(data);
        if (state.selectedSession) {
          renderSessionDetail(state.selectedSession);
        } else if (state.selectedTopic) {
          renderTopicDetail(state.selectedTopic);
        }
      } catch (err) {
        document.getElementById("generated").textContent = `error: ${err.message || err}`;
      }
    }

    attachHandlers();
    tick();
    setInterval(tick, REFRESH_MS);
  </script>
</body>
</html>
"""


def _env(name: str) -> str | None:
    val = os.environ.get(name)
    if val:
        return val
    return None


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _to_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _iso_from_epoch_ms(value: object) -> str | None:
    ms = _to_int(value)
    if ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _shorten(value: str, limit: int = _MESSAGE_SUMMARY_MAX) -> str:
    text = value.strip().replace("\r", "")
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _decode_message_body(body: object) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(body, str) or not body.strip():
        return None, None
    try:
        payload = json.loads(body)
    except Exception:
        return None, {"text": _shorten(body)}

    if isinstance(payload, dict):
        schema = payload.get("schema")
        if isinstance(schema, str) and isinstance(payload.get("data"), dict):
            return schema, payload["data"]
        return None, payload
    return None, None


def _extract_summary_from_payload(payload: dict[str, Any]) -> str:
    if "decision" in payload or "summary" in payload:
        decision = str(payload.get("decision") or "")
        summary = str(payload.get("summary") or "")
        if decision and summary:
            return _shorten(f"{decision}: {summary}")
        if summary:
            return _shorten(summary)
    if "phase" in payload and "summary" in payload:
        phase = str(payload.get("phase") or "")
        summary = str(payload.get("summary") or "")
        if phase and summary:
            return _shorten(f"{phase}: {summary}")
    if "text" in payload:
        return _shorten(str(payload.get("text") or ""))
    return _shorten(json.dumps(payload, ensure_ascii=False))


@dataclass
class MonitorConfig:
    repo_root: Path
    host: str
    port: int
    refresh_seconds: int
    cache_ttl_seconds: int
    max_sessions: int
    max_issues: int
    max_topics: int


class MonitorCollector:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.forum = Forum.from_workdir(repo_root)
        self.issue = Issue.from_workdir(repo_root)

    def _forum_topics(self) -> list[dict[str, Any]]:
        return self.forum.list_topics()

    def _forum_read(self, topic: str, *, limit: int) -> list[dict[str, Any]]:
        return self.forum.read(topic, limit=limit)

    def _issue_list(self, status: str) -> list[dict[str, Any]]:
        return self.issue.list(status=status, limit=1000)

    def _matching_session_topics(
        self, topics: list[dict[str, Any]]
    ) -> list[tuple[str, str, dict[str, Any]]]:
        matches: list[tuple[str, str, dict[str, Any]]] = []
        for topic in topics:
            name = topic.get("name")
            if not isinstance(name, str):
                continue
            match = _SESSION_TOPIC_RE.match(name)
            if not match:
                continue
            prefix = match.group("prefix")
            session_id = match.group("session_id")
            matches.append((prefix, session_id, topic))

        matches.sort(key=lambda item: _to_int(item[2].get("created_at")) or 0, reverse=True)
        return matches

    def _latest_session_meta(self, topic_name: str) -> dict[str, Any]:
        messages = self._forum_read(topic_name, limit=8)
        latest_key = -1
        latest_meta: dict[str, Any] | None = None

        for message in messages:
            schema, payload = _decode_message_body(message.get("body"))
            if payload is None:
                continue
            if schema and not schema.endswith("session.meta.v1"):
                continue
            if "prompt" not in payload and "status" not in payload and "started" not in payload:
                continue
            created = _to_int(message.get("created_at")) or _to_int(message.get("id")) or 0
            if created >= latest_key:
                latest_key = created
                latest_meta = payload

        return latest_meta or {}

    def _latest_status(self, prefix: str, session_id: str) -> tuple[str | None, str | None]:
        topic = f"{prefix}:status:{session_id}"
        messages = self._forum_read(topic, limit=2)
        for message in messages:
            _, payload = _decode_message_body(message.get("body"))
            if not isinstance(payload, dict):
                continue
            decision = payload.get("decision")
            summary = payload.get("summary")
            if decision is None and summary is None:
                continue
            return (
                str(decision) if decision is not None else None,
                str(summary) if summary is not None else None,
            )
        return None, None

    def _briefings(self, prefix: str, session_id: str, *, limit: int = 4) -> list[dict[str, Any]]:
        topic = f"{prefix}:briefing:{session_id}"
        messages = self._forum_read(topic, limit=max(limit, 8))
        rows: list[tuple[int, dict[str, Any]]] = []
        for message in messages:
            schema, payload = _decode_message_body(message.get("body"))
            if not isinstance(payload, dict):
                continue
            if schema and not schema.endswith("session.briefing.v1"):
                continue
            if "phase" not in payload and "summary" not in payload:
                continue
            created = _to_int(message.get("created_at")) or _to_int(message.get("id")) or 0
            rows.append((created, payload))

        rows.sort(key=lambda item: item[0], reverse=True)
        out: list[dict[str, Any]] = []
        for _, payload in rows[:limit]:
            out.append(
                {
                    "phase": payload.get("phase"),
                    "iteration": payload.get("iteration"),
                    "summary": str(payload.get("summary") or "").strip(),
                    "timestamp": payload.get("timestamp"),
                }
            )
        return out

    def _latest_forward(self, prefix: str, session_id: str) -> dict[str, Any]:
        topic = f"{prefix}:forward:{session_id}"
        messages = self._forum_read(topic, limit=1)
        if not messages:
            return {}
        _, payload = _decode_message_body(messages[0].get("body"))
        if isinstance(payload, dict):
            return payload
        return {}

    def _collect_sessions(self, max_sessions: int) -> list[dict[str, Any]]:
        topics = self._forum_topics()
        session_topics = self._matching_session_topics(topics)
        rows: list[dict[str, Any]] = []
        for prefix, session_id, topic in session_topics[:max_sessions]:
            topic_name = str(topic.get("name") or "")
            meta = self._latest_session_meta(topic_name)
            decision, decision_summary = self._latest_status(prefix, session_id)
            briefings = self._briefings(prefix, session_id)
            forward = self._latest_forward(prefix, session_id)
            latest_summary = briefings[0]["summary"] if briefings else ""
            rows.append(
                {
                    "prefix": prefix,
                    "topic": topic_name,
                    "session_id": session_id,
                    "prompt": str(meta.get("prompt") or "").strip(),
                    "status": str(meta.get("status") or "unknown").strip(),
                    "phase": meta.get("phase"),
                    "iteration": meta.get("iteration"),
                    "started": meta.get("started"),
                    "ended": meta.get("ended"),
                    "started_iso": meta.get("started") or _iso_from_epoch_ms(topic.get("created_at")),
                    "ended_iso": meta.get("ended"),
                    "decision": decision,
                    "decision_summary": decision_summary,
                    "latest_summary": latest_summary,
                    "briefings": briefings,
                    "forward_summary": forward.get("summary"),
                    "forward_post_head": forward.get("post_head"),
                }
            )

        rows.sort(key=lambda row: str(row.get("started") or ""), reverse=True)
        return rows

    def _collect_issues(
        self, max_issues: int
    ) -> tuple[dict[str, int], list[dict[str, Any]]]:
        statuses = ("in_progress", "open", "paused")
        by_status: dict[str, list[dict[str, Any]]] = {
            status: self._issue_list(status) for status in statuses
        }
        counts: dict[str, int] = {status: len(by_status[status]) for status in statuses}

        merged: list[dict[str, Any]] = []
        for status, issues in by_status.items():
            for issue in issues:
                issue = dict(issue)
                issue["status"] = status
                issue["updated_at_iso"] = _iso_from_epoch_ms(issue.get("updated_at"))
                merged.append(issue)

        status_rank = {"in_progress": 0, "open": 1, "paused": 2}

        def key_fn(issue: dict[str, Any]) -> tuple[int, int, int]:
            priority = _to_int(issue.get("priority"))
            updated = _to_int(issue.get("updated_at")) or 0
            return (
                status_rank.get(str(issue.get("status")), 9),
                priority if priority is not None else 99,
                -updated,
            )

        merged.sort(key=key_fn)
        trimmed = merged[:max_issues]
        return counts, trimmed

    def _collect_forum_topics(self, max_topics: int) -> list[dict[str, Any]]:
        topics = self._forum_topics()
        rows: list[dict[str, Any]] = []
        for topic in topics:
            name = topic.get("name")
            if not isinstance(name, str):
                continue
            created_at = _to_int(topic.get("created_at"))
            rows.append(
                {
                    "name": name,
                    "kind": name.split(":", 1)[0],
                    "created_at": created_at,
                    "created_at_iso": _iso_from_epoch_ms(created_at),
                }
            )

        rows.sort(key=lambda item: item.get("created_at") or 0, reverse=True)
        return rows[:max_topics]

    def collect_topic_messages(
        self, topic_name: str, *, limit: int = 20
    ) -> dict[str, Any]:
        messages = self._forum_read(topic_name, limit=max(1, min(limit, 100)))
        rows: list[dict[str, Any]] = []
        for message in messages:
            body = message.get("body")
            _, payload = _decode_message_body(body)
            if isinstance(payload, dict):
                summary = _extract_summary_from_payload(payload)
            else:
                summary = _shorten(str(body or ""))
            created_at = _to_int(message.get("created_at"))
            rows.append(
                {
                    "id": message.get("id"),
                    "created_at": created_at,
                    "created_at_iso": _iso_from_epoch_ms(created_at),
                    "summary": summary,
                }
            )

        rows.sort(key=lambda item: item.get("created_at") or 0, reverse=True)
        return {"topic": topic_name, "messages": rows}

    def collect_overview(
        self,
        *,
        max_sessions: int,
        max_issues: int,
        max_topics: int,
    ) -> dict[str, Any]:
        issue_counts, issues = self._collect_issues(max_issues)
        return {
            "generated_at": utc_now_iso(),
            "host": socket.gethostname(),
            "health": {
                "forum_db": self.forum.store.db_path.exists(),
                "issue_db": self.issue.store.db_path.exists(),
            },
            "sessions": self._collect_sessions(max_sessions),
            "issue_counts": issue_counts,
            "issues": issues,
            "forum_topics": self._collect_forum_topics(max_topics),
        }


class SnapshotCache:
    def __init__(
        self,
        collector: MonitorCollector,
        *,
        ttl_seconds: int,
        max_sessions: int,
        max_issues: int,
        max_topics: int,
    ) -> None:
        self.collector = collector
        self.ttl_seconds = max(1, ttl_seconds)
        self.max_sessions = max_sessions
        self.max_issues = max_issues
        self.max_topics = max_topics
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._stamp = 0.0

    def get(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if self._snapshot is not None and (now - self._stamp) < self.ttl_seconds:
                return self._snapshot

        snapshot = self.collector.collect_overview(
            max_sessions=self.max_sessions,
            max_issues=self.max_issues,
            max_topics=self.max_topics,
        )
        with self._lock:
            self._snapshot = snapshot
            self._stamp = time.monotonic()
        return snapshot


class MonitorHandler(BaseHTTPRequestHandler):
    collector: MonitorCollector
    cache: SnapshotCache
    refresh_seconds: int

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._serve_html()
            return
        if path == "/healthz":
            self._send_json(200, {"ok": True, "time": utc_now_iso()})
            return
        if path == "/api/overview":
            self._send_json(200, self.cache.get())
            return
        if path.startswith("/api/session/"):
            session_id = unquote(path[len("/api/session/") :])
            data = self.cache.get()
            session = next(
                (item for item in data.get("sessions", []) if item.get("session_id") == session_id),
                None,
            )
            if session is None:
                self._send_json(404, {"error": "session not found"})
                return
            self._send_json(200, session)
            return
        if path == "/api/topic":
            query = parse_qs(parsed.query)
            names = query.get("name") or []
            if not names:
                self._send_json(400, {"error": "missing topic name"})
                return
            limit_raw = (query.get("limit") or ["20"])[0]
            try:
                limit = int(limit_raw)
            except ValueError:
                limit = 20
            payload = self.collector.collect_topic_messages(names[0], limit=limit)
            self._send_json(200, payload)
            return

        self._send_json(404, {"error": "not found"})

    def _serve_html(self) -> None:
        html = _HTML_TEMPLATE.replace("__REFRESH_MS__", str(self.refresh_seconds * 1000))
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loopfarm monitor")
    parser.add_argument(
        "--host",
        default=_env("LOOPFARM_MONITOR_HOST") or "0.0.0.0",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("LOOPFARM_MONITOR_PORT", 8765),
    )
    parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=_env_int("LOOPFARM_MONITOR_REFRESH_SECONDS", 8),
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=_env_int("LOOPFARM_MONITOR_CACHE_TTL", 4),
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=_env_int("LOOPFARM_MONITOR_MAX_SESSIONS", 12),
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=_env_int("LOOPFARM_MONITOR_MAX_ISSUES", 24),
    )
    parser.add_argument(
        "--max-topics",
        type=int,
        default=_env_int("LOOPFARM_MONITOR_MAX_TOPICS", 24),
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Working directory used for .loopfarm state discovery",
    )
    return parser


def _make_handler(
    collector: MonitorCollector, cache: SnapshotCache, refresh_seconds: int
) -> type[MonitorHandler]:
    class _Handler(MonitorHandler):
        pass

    _Handler.collector = collector
    _Handler.cache = cache
    _Handler.refresh_seconds = refresh_seconds
    return _Handler


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    cfg = MonitorConfig(
        repo_root=Path(args.repo_root).resolve(),
        host=str(args.host),
        port=max(1, int(args.port)),
        refresh_seconds=max(2, int(args.refresh_seconds)),
        cache_ttl_seconds=max(1, int(args.cache_ttl)),
        max_sessions=max(1, int(args.max_sessions)),
        max_issues=max(1, int(args.max_issues)),
        max_topics=max(1, int(args.max_topics)),
    )

    collector = MonitorCollector(cfg.repo_root)
    cache = SnapshotCache(
        collector,
        ttl_seconds=cfg.cache_ttl_seconds,
        max_sessions=cfg.max_sessions,
        max_issues=cfg.max_issues,
        max_topics=cfg.max_topics,
    )

    handler_cls = _make_handler(collector, cache, cfg.refresh_seconds)
    server = ThreadingHTTPServer((cfg.host, cfg.port), handler_cls)
    print(
        f"loopfarm monitor listening on http://{cfg.host}:{cfg.port} "
        f"(repo={cfg.repo_root})",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
