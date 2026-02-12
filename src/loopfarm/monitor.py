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

from .runtime.config import ProgramFileConfig, load_config
from .forum import Forum
from .issue import Issue
from .runner import CodexPhaseModel, LoopfarmConfig, run_loop
from .stores.issue import ISSUE_STATUSES
from .stores.session import SessionStore
from .util import utc_now_iso
from .util import new_session_id

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
      --emes-font-sans: "Univers LT Pro", -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
      --emes-font-mono: "Berkeley Mono", "TX-02-Data", "Roboto Mono", Menlo, Courier, monospace;
      --emes-black: #000;
      --emes-white: #fff;
      --emes-blue: #002dce;
      --emes-gold: #ffb700;
      --emes-dark-green: #00794c;
      --emes-red: #e7040f;
      --emes-gray-900: #111;
      --emes-gray-700: #555;
      --emes-gray-600: #777;
      --emes-gray-500: #999;
      --emes-gray-300: #bbb;
      --emes-gray-200: #ccc;
      --emes-gray-100: #ddd;
      --emes-gray-50: #eee;
      --emes-gray-25: #f9fafb;
      --emes-shadow: 2px 2px var(--emes-gray-300);
      --emes-dot-pattern: radial-gradient(var(--emes-gray-600) 0.5px, transparent 1px) 0 0 / 3px 3px;
    }
    * { box-sizing: border-box; }
    html {
      font-family: var(--emes-font-sans);
      font-size: 15px;
      line-height: 1.45;
      background: var(--emes-gray-50);
    }
    body {
      margin: 0;
      color: var(--emes-black);
      background: var(--emes-white);
      text-rendering: optimizeLegibility;
    }
    .top {
      position: sticky;
      top: 0;
      z-index: 20;
      background: var(--emes-white);
      border-bottom: 2px solid var(--emes-black);
      padding: 0.75rem 1rem;
      display: grid;
      gap: 0.6rem;
    }
    .brand-row {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 0.75rem;
      flex-wrap: wrap;
    }
    .brand {
      font-size: 0.9rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .subtitle {
      font-size: 0.8rem;
      color: var(--emes-gray-600);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .status-bar {
      display: flex;
      align-items: center;
      gap: 0.9rem;
      padding: 0.35rem 0.5rem;
      background: var(--emes-gray-25);
      border: 1px solid var(--emes-black);
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .status-bar-item {
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border: 1px solid var(--emes-black);
      border-radius: 50%;
      background: var(--emes-dark-green);
    }
    .query-meta {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0.45rem;
      padding: 0.45rem;
      border: 1px solid var(--emes-black);
      background: var(--emes-gray-25);
    }
    .query-meta-item {
      border: 1px solid var(--emes-gray-300);
      background: var(--emes-white);
      padding: 0.3rem 0.4rem;
      min-height: 46px;
    }
    .query-meta-label {
      display: block;
      font-size: 0.68rem;
      color: var(--emes-gray-600);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .query-meta-value {
      display: block;
      margin-top: 0.1rem;
      font-family: var(--emes-font-mono);
      font-size: 1rem;
      font-weight: 700;
    }
    .metrics {
      display: none;
    }
    .box {
      position: relative;
      border: 2px solid var(--emes-black);
      background: var(--emes-white);
      padding: 0.65rem;
      margin: 0;
    }
    .box[data-label]::before {
      content: attr(data-label);
      position: absolute;
      top: -0.6rem;
      left: 0.7rem;
      background: var(--emes-white);
      padding: 0 0.35rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.7rem;
      font-weight: 700;
    }
    .box-shadow {
      box-shadow: var(--emes-shadow);
    }
    .filter-row {
      display: grid;
      grid-template-columns: 1fr;
      gap: 0.5rem;
      align-items: center;
    }
    .actions-row {
      display: grid;
      gap: 0.45rem;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      align-items: center;
      margin-top: 0.35rem;
    }
    .actions-row.tight {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .input-brutal,
    .select-brutal,
    .textarea-brutal {
      width: 100%;
      border: 1px solid var(--emes-black);
      border-radius: 0;
      padding: 0.42rem 0.55rem;
      background: var(--emes-white);
      color: var(--emes-black);
      font: inherit;
      box-shadow: var(--emes-shadow);
    }
    .input-brutal:focus,
    .select-brutal:focus,
    .textarea-brutal:focus {
      outline: 2px solid var(--emes-blue);
      outline-offset: 1px;
    }
    .btn-brutal {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0.44rem 0.8rem;
      border: 1px solid var(--emes-black);
      background: var(--emes-white);
      color: var(--emes-black);
      text-transform: lowercase;
      font-size: 0.86rem;
      font-weight: 600;
      cursor: pointer;
      box-shadow: var(--emes-shadow);
    }
    .btn-brutal:hover {
      background: var(--emes-black);
      color: var(--emes-white);
    }
    .btn-brutal:active {
      box-shadow: none;
      transform: translate(2px, 2px);
    }
    .btn-brutal:disabled {
      opacity: 0.45;
      cursor: not-allowed;
      pointer-events: none;
    }
    .btn-brutal-primary {
      background: var(--emes-gold);
    }
    .btn-brutal-green {
      background: var(--emes-dark-green);
      color: var(--emes-white);
    }
    .btn-brutal-green:hover {
      background: var(--emes-dark-green);
      color: var(--emes-white);
      filter: brightness(0.92);
    }
    .btn-danger {
      background: var(--emes-red);
      color: var(--emes-white);
    }
    .btn-danger:hover {
      background: var(--emes-red);
      color: var(--emes-white);
      filter: brightness(0.92);
    }
    .panel-actions {
      padding: 0.5rem;
      border: 1px solid var(--emes-black);
      background: var(--emes-gray-25);
      margin-bottom: 0.6rem;
    }
    .panel-actions .label {
      color: var(--emes-gray-700);
      margin-bottom: 0.1rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-size: 0.7rem;
      font-weight: 700;
    }
    .panel-actions.disabled {
      opacity: 0.6;
    }
    .container {
      display: grid;
      gap: 0.85rem;
      padding: 0.95rem;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem;
      border-bottom: 1px solid var(--emes-gray-300);
      padding-bottom: 0.6rem;
      margin-bottom: 0.35rem;
    }
    .btn-nav {
      min-width: 110px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.72rem;
    }
    .btn-nav.is-active {
      background: var(--emes-black);
      color: var(--emes-white);
    }
    .tab-pane {
      display: none;
    }
    .tab-pane.is-active {
      display: block;
    }
    .tab-layout {
      display: grid;
      gap: 0.85rem;
    }
    .selection-badge {
      border: 1px dashed var(--emes-gray-600);
      padding: 0.35rem 0.45rem;
      background: var(--emes-gray-25);
      margin-bottom: 0.45rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .panel {
      background: var(--emes-white);
      overflow: hidden;
    }
    .panel h2 {
      margin: 0;
      padding: 0;
      background: transparent;
      border-bottom: 1px solid var(--emes-gray-300);
      font-size: 0.8rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 0.45rem;
      padding-bottom: 0.35rem;
    }
    .scroll {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }
    table.table-brutal {
      width: 100%;
      border-collapse: collapse;
      white-space: nowrap;
    }
    .table-brutal th,
    .table-brutal td {
      border: 1px solid var(--emes-black);
      padding: 0.45rem 0.5rem;
      text-align: left;
      vertical-align: top;
    }
    .table-brutal th {
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-size: 0.66rem;
      color: var(--emes-gray-700);
      background: var(--emes-gray-25);
      font-weight: 700;
    }
    .table-brutal tbody tr:hover {
      background: #f5f7ff;
      cursor: pointer;
    }
    .table-brutal tbody tr.is-selected {
      background: #fff3cf;
    }
    .status-running { color: var(--emes-dark-green); font-weight: 700; }
    .status-complete { color: var(--emes-blue); font-weight: 700; }
    .status-interrupted, .status-stopped { color: #9a5800; font-weight: 700; }
    .status-failed, .status-error { color: var(--emes-red); font-weight: 700; }
    .mono-pre {
      margin: 0;
      padding: 0.6rem;
      max-height: 340px;
      overflow: auto;
      border: 1px solid var(--emes-black);
      background: var(--emes-gray-25);
      white-space: pre-wrap;
      word-break: break-word;
      font-family: var(--emes-font-mono);
      font-size: 0.82rem;
      line-height: 1.35;
    }
    .hint {
      color: var(--emes-gray-700);
      font-size: 0.78rem;
      padding: 0.35rem 0;
    }
    .workflow-list {
      margin: 0.2rem 0 0;
      padding-left: 1.15rem;
      font-size: 0.82rem;
      line-height: 1.3;
    }
    .workflow-list li {
      margin: 0.28rem 0;
    }
    #action-status {
      border: 1px solid var(--emes-gray-300);
      padding: 0.4rem 0.5rem;
      min-height: 2rem;
      background: var(--emes-gray-25);
      font-size: 0.82rem;
      font-family: var(--emes-font-mono);
    }
    #action-status.ok {
      border-color: var(--emes-dark-green);
      background: #eef8f3;
      color: var(--emes-dark-green);
    }
    #action-status.warn {
      border-color: #9a5800;
      background: #fff6e6;
      color: #9a5800;
    }
    #action-status.err {
      border-color: var(--emes-red);
      background: #fff0f0;
      color: var(--emes-red);
    }
    .topic-msg {
      border: 1px solid var(--emes-black);
      margin-top: 0.3rem;
      padding: 0.45rem 0.5rem;
      background: var(--emes-white);
    }
    .topic-msg .meta {
      color: var(--emes-gray-700);
      font-size: 0.72rem;
      font-family: var(--emes-font-mono);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .topic-msg .body {
      margin-top: 0.15rem;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: var(--emes-font-mono);
      font-size: 0.8rem;
    }
    @media (max-width: 980px) {
      .query-meta {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .actions-row,
      .actions-row.tight {
        grid-template-columns: 1fr;
      }
      .top {
        position: static;
      }
    }
    @media (min-width: 1120px) {
      .tab-layout.two-col {
        grid-template-columns: 1.15fr 1fr;
      }
    }
  </style>
</head>
<body>
  <header class="top">
    <div class="brand-row">
      <div>
        <span class="brand">loopfarm operator console</span>
        <span class="subtitle">frontend control plane for programmable loops</span>
      </div>
      <span id="generated" class="hint"></span>
    </div>
    <div class="status-bar">
      <div class="status-bar-item"><span class="status-dot"></span><span>monitor online</span></div>
      <div class="status-bar-item"><span>host</span><span id="host" class="query-meta-value">-</span></div>
      <div class="status-bar-item"><span>selection</span><span id="selection-status" class="query-meta-value">none</span></div>
    </div>
    <div class="query-meta">
      <div class="query-meta-item"><span class="query-meta-label">active loops</span><span id="m-active" class="query-meta-value">-</span></div>
      <div class="query-meta-item"><span class="query-meta-label">in progress issues</span><span id="m-inprogress" class="query-meta-value">-</span></div>
      <div class="query-meta-item"><span class="query-meta-label">open issues</span><span id="m-open" class="query-meta-value">-</span></div>
      <div class="query-meta-item"><span class="query-meta-label">forum topics</span><span id="m-topics" class="query-meta-value">-</span></div>
    </div>
    <div class="box box-shadow" data-label="Quick Start">
      <ol class="workflow-list">
        <li>Enter a prompt under <strong>Start New Loop</strong>, then click <strong>start loop</strong>.</li>
        <li>Select a row in <strong>Loops</strong> to inspect output and use pause/resume/stop/context controls.</li>
        <li>Select a row in <strong>Issues</strong> to inspect details, then update status/comment in-place.</li>
        <li>Select a <strong>Forum Topic</strong> to read messages; use post form to inject instructions/state.</li>
      </ol>
    </div>
    <div class="box box-shadow" data-label="Start New Loop">
      <div class="actions-row">
        <input class="input-brutal" id="start-prompt" type="text" placeholder="new loop prompt" />
        <input class="input-brutal" id="start-program" type="text" placeholder="program (optional)" />
        <input class="input-brutal" id="start-project" type="text" placeholder="project override (optional)" />
        <button class="btn-brutal btn-brutal-primary" id="start-loop">start loop</button>
      </div>
    </div>
    <div class="filter-row">
      <input class="input-brutal" id="filter" type="text" placeholder="filter loops/issues/topics (id, status, title, prompt, tag)" />
    </div>
    <div id="action-status">ready.</div>
  </header>

  <main class="container">
    <nav class="tabs" role="tablist" aria-label="Loopfarm domains">
      <button class="btn-brutal btn-nav is-active" id="tab-btn-loops" data-tab="loops" role="tab" aria-controls="tab-loops">loops</button>
      <button class="btn-brutal btn-nav" id="tab-btn-issues" data-tab="issues" role="tab" aria-controls="tab-issues">issues</button>
      <button class="btn-brutal btn-nav" id="tab-btn-forum" data-tab="forum" role="tab" aria-controls="tab-forum">forum</button>
    </nav>

    <section id="tab-loops" class="tab-pane is-active" role="tabpanel">
      <div class="tab-layout two-col">
        <section class="panel box box-shadow">
          <h2>Loops</h2>
          <div class="hint">Start new loop runs, then select a session row to inspect details and send controls.</div>
          <div class="scroll">
            <table class="table-brutal">
              <thead>
                <tr><th>Session</th><th>Status</th><th>Phase</th><th>Iter</th><th>Started</th><th>Prompt</th></tr>
              </thead>
              <tbody id="sessions-body"></tbody>
            </table>
          </div>
        </section>
        <section class="panel box box-shadow">
          <h2>Loop Detail</h2>
          <div id="loops-details-context" class="selection-badge">Selected: none</div>
          <div id="loops-details-empty" class="hint">Select a loop session from the loops table.</div>
          <pre id="loops-details-pre" class="mono-pre" style="display:none"></pre>
          <div id="session-controls" class="panel-actions disabled">
            <div class="label">Session Controls</div>
            <div class="actions-row tight">
              <button class="btn-brutal" id="session-pause">pause</button>
              <button class="btn-brutal btn-brutal-green" id="session-resume">resume</button>
              <button class="btn-brutal btn-danger" id="session-stop">stop</button>
            </div>
            <div class="actions-row">
              <input class="input-brutal" id="session-context" type="text" placeholder="session context override" />
              <input class="input-brutal" id="session-author" type="text" placeholder="author (optional)" />
              <button class="btn-brutal" id="session-context-set">set context</button>
              <button class="btn-brutal" id="session-context-clear">clear context</button>
            </div>
          </div>
        </section>
      </div>
    </section>

    <section id="tab-issues" class="tab-pane" role="tabpanel">
      <div class="tab-layout two-col">
        <section class="panel box box-shadow">
          <h2>Issues</h2>
          <div class="hint">Create and update tracker items. Selecting a row opens full detail and dependency graph.</div>
          <div class="panel-actions">
            <div class="label">Create Issue</div>
            <div class="actions-row">
              <input class="input-brutal" id="issue-title" type="text" placeholder="issue title" />
              <input class="input-brutal" id="issue-tags" type="text" placeholder="tags (comma-separated)" />
              <select class="select-brutal" id="issue-priority">
                <option value="1">P1</option>
                <option value="2">P2</option>
                <option value="3" selected>P3</option>
                <option value="4">P4</option>
                <option value="5">P5</option>
              </select>
              <button class="btn-brutal" id="issue-create">create</button>
            </div>
            <div class="label">Update Selected Issue</div>
            <div class="actions-row">
              <input class="input-brutal" id="issue-selected" type="text" placeholder="select an issue row" readonly />
              <select class="select-brutal" id="issue-status">
                <option value="open">open</option>
                <option value="in_progress">in_progress</option>
                <option value="paused">paused</option>
                <option value="closed">closed</option>
              </select>
              <input class="input-brutal" id="issue-comment" type="text" placeholder="comment for selected issue" />
              <button class="btn-brutal" id="issue-update">apply</button>
            </div>
          </div>
          <div class="scroll">
            <table class="table-brutal">
              <thead>
                <tr><th>ID</th><th>St</th><th>P</th><th>Updated</th><th>Title</th></tr>
              </thead>
              <tbody id="issues-body"></tbody>
            </table>
          </div>
        </section>
        <section class="panel box box-shadow">
          <h2>Issue Detail</h2>
          <div id="issues-details-context" class="selection-badge">Selected: none</div>
          <div id="issues-details-empty" class="hint">Select an issue row from the issues table.</div>
          <pre id="issues-details-pre" class="mono-pre" style="display:none"></pre>
        </section>
      </div>
    </section>

    <section id="tab-forum" class="tab-pane" role="tabpanel">
      <div class="tab-layout two-col">
        <section class="panel box box-shadow">
          <h2>Forum Topics</h2>
          <div class="hint">Post loop instructions/state to a topic, then select topics to inspect full message history.</div>
          <div class="panel-actions">
            <div class="label">Post Message</div>
            <div class="actions-row">
              <input class="input-brutal" id="forum-topic" type="text" placeholder="topic name" />
              <input class="input-brutal" id="forum-author" type="text" placeholder="author (optional)" />
              <input class="input-brutal" id="forum-message" type="text" placeholder="message" />
              <button class="btn-brutal" id="forum-post">post</button>
            </div>
          </div>
          <div class="scroll">
            <table class="table-brutal">
              <thead>
                <tr><th>Topic</th><th>Type</th><th>Created</th></tr>
              </thead>
              <tbody id="topics-body"></tbody>
            </table>
          </div>
        </section>
        <section class="panel box box-shadow">
          <h2>Topic Detail</h2>
          <div id="forum-details-context" class="selection-badge">Selected: none</div>
          <div id="forum-details-empty" class="hint">Select a forum topic row from the topics table.</div>
          <pre id="forum-details-pre" class="mono-pre" style="display:none"></pre>
          <div id="forum-topic-messages"></div>
        </section>
      </div>
    </section>
  </main>

  <script>
    const REFRESH_MS = __REFRESH_MS__;
    const state = {
      data: null,
      meta: null,
      filter: "",
      selectedSession: null,
      selectedTopic: null,
      selectedIssue: null,
      activeTab: "loops",
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

    function showActionStatus(message, level = "info") {
      const node = document.getElementById("action-status");
      node.textContent = message || "";
      node.classList.remove("ok", "warn", "err");
      if (level === "ok" || level === "warn" || level === "err") {
        node.classList.add(level);
      }
    }

    function setSelectionStatus(value) {
      document.getElementById("selection-status").textContent = value || "none";
    }

    function setPanelSelection(panel, value) {
      const el = document.getElementById(`${panel}-details-context`);
      if (el) {
        el.textContent = value ? `Selected: ${value}` : "Selected: none";
      }
    }

    function setActiveTab(tab) {
      state.activeTab = tab;
      const tabs = ["loops", "issues", "forum"];
      for (const name of tabs) {
        const btn = document.getElementById(`tab-btn-${name}`);
        const pane = document.getElementById(`tab-${name}`);
        if (btn) btn.classList.toggle("is-active", name === tab);
        if (pane) pane.classList.toggle("is-active", name === tab);
      }
    }

    function setSessionControlsVisible(enabled) {
      const controls = document.getElementById("session-controls");
      controls.classList.toggle("disabled", !enabled);
      const ids = [
        "session-pause",
        "session-resume",
        "session-stop",
        "session-context",
        "session-author",
        "session-context-set",
        "session-context-clear",
      ];
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el) el.disabled = !enabled;
      }
    }

    function resetLoopDetail() {
      setSessionControlsVisible(false);
      setPanelSelection("loops", null);
      const empty = document.getElementById("loops-details-empty");
      const pre = document.getElementById("loops-details-pre");
      empty.textContent = "Select a loop session from the loops table.";
      empty.style.display = "block";
      pre.style.display = "none";
      pre.textContent = "";
    }

    function resetIssueDetail() {
      setPanelSelection("issues", null);
      const empty = document.getElementById("issues-details-empty");
      const pre = document.getElementById("issues-details-pre");
      empty.textContent = "Select an issue row from the issues table.";
      empty.style.display = "block";
      pre.style.display = "none";
      pre.textContent = "";
    }

    function resetForumDetail() {
      setPanelSelection("forum", null);
      const empty = document.getElementById("forum-details-empty");
      const pre = document.getElementById("forum-details-pre");
      const messages = document.getElementById("forum-topic-messages");
      empty.textContent = "Select a forum topic row from the topics table.";
      empty.style.display = "block";
      pre.style.display = "none";
      pre.textContent = "";
      messages.innerHTML = "";
    }

    async function apiGet(url) {
      const resp = await fetch(url, { cache: "no-store" });
      if (!resp.ok) {
        let err = `status ${resp.status}`;
        try {
          const payload = await resp.json();
          if (payload && payload.error) err = payload.error;
        } catch (_) {}
        throw new Error(err);
      }
      return await resp.json();
    }

    async function apiPost(url, payload) {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(payload || {}),
      });
      if (!resp.ok) {
        let err = `status ${resp.status}`;
        try {
          const body = await resp.json();
          if (body && body.error) err = body.error;
        } catch (_) {}
        throw new Error(err);
      }
      return await resp.json();
    }

    function applyMetrics(data) {
      const counts = data.issue_counts || {};
      document.getElementById("generated").textContent = `updated ${fmtTime(data.generated_at)} · refresh ${Math.round(REFRESH_MS / 1000)}s`;
      document.getElementById("host").textContent = String(data.host || "-");
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
        const rowClass = state.selectedSession === s.session_id ? "is-selected" : "";
        return `<tr class="${rowClass}" data-kind="session" data-id="${esc(s.session_id)}">`
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
        const statusClass = `status-${String(i.status || "").toLowerCase()}`;
        const rowClass = state.selectedIssue === i.id ? "is-selected" : "";
        return `<tr class="${rowClass}" data-kind="issue" data-id="${esc(i.id)}">`
          + `<td>${esc(i.id)}</td>`
          + `<td class="${statusClass}">${esc(i.status)}</td>`
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
        const rowClass = state.selectedTopic === t.name ? "is-selected" : "";
        return `<tr class="${rowClass}" data-kind="topic" data-name="${esc(t.name)}">`
          + `<td>${esc(t.name)}</td>`
          + `<td>${esc(t.kind)}</td>`
          + `<td>${esc(fmtTime(t.created_at_iso || t.created_at))}</td>`
          + `</tr>`;
      }).join("");
      document.getElementById("topics-body").innerHTML = html || `<tr><td colspan="3" class="hint">No matching topics.</td></tr>`;
    }

    function renderSessionDetail(sessionId) {
      const detailsPre = document.getElementById("loops-details-pre");
      const detailsEmpty = document.getElementById("loops-details-empty");
      setSessionControlsVisible(true);
      setPanelSelection("loops", `session ${sessionId}`);
      setSelectionStatus(`session:${sessionId}`);
      const session = (state.data.sessions || []).find((s) => s.session_id === sessionId);
      if (!session) {
        detailsEmpty.style.display = "block";
        detailsEmpty.textContent = `Session not found: ${sessionId}`;
        detailsPre.style.display = "none";
        setSessionControlsVisible(false);
        setPanelSelection("loops", null);
        setSelectionStatus("none");
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

    async function renderIssueDetail(issueId) {
      const detailsPre = document.getElementById("issues-details-pre");
      const detailsEmpty = document.getElementById("issues-details-empty");
      setPanelSelection("issues", `issue ${issueId}`);
      setSelectionStatus(`issue:${issueId}`);
      detailsEmpty.style.display = "none";
      detailsPre.style.display = "none";
      detailsPre.textContent = "";
      try {
        const issue = await apiGet(`/api/issues/${encodeURIComponent(issueId)}`);
        const lines = [];
        lines.push(`issue:     ${issue.id || "-"}`);
        lines.push(`status:    ${issue.status || "-"}`);
        lines.push(`priority:  P${issue.priority ?? "-"}`);
        lines.push(`created:   ${fmtTime(issue.created_at_iso || issue.created_at)}`);
        lines.push(`updated:   ${fmtTime(issue.updated_at_iso || issue.updated_at)}`);
        lines.push(`title:     ${issue.title || ""}`);
        lines.push("");
        lines.push("body:");
        lines.push(issue.body || "-");
        lines.push("");
        lines.push("dependencies:");
        const deps = issue.dependencies || [];
        if (!deps.length) {
          lines.push("  (none)");
        } else {
          for (const dep of deps) {
            lines.push(`  ${dep.src_id} ${dep.type} ${dep.dst_id} (${dep.direction || "?"}, active=${dep.active ? "yes" : "no"})`);
          }
        }
        lines.push("");
        lines.push("comments:");
        const comments = issue.comments || [];
        if (!comments.length) {
          lines.push("  (none)");
        } else {
          for (const c of comments) {
            lines.push(`  [${c.id}] ${c.author || "unknown"} @ ${fmtTime(c.created_at_iso || c.created_at)}`);
            lines.push(`  ${c.body || ""}`);
          }
        }
        detailsPre.textContent = lines.join("\n");
        detailsPre.style.display = "block";
      } catch (err) {
        detailsPre.textContent = `failed to load issue ${issueId}: ${err.message || err}`;
        detailsPre.style.display = "block";
      }
    }

    async function renderTopicDetail(topicName) {
      const detailsPre = document.getElementById("forum-details-pre");
      const detailsEmpty = document.getElementById("forum-details-empty");
      const topicMessages = document.getElementById("forum-topic-messages");
      setPanelSelection("forum", `topic ${topicName}`);
      setSelectionStatus(`topic:${topicName}`);
      detailsPre.style.display = "none";
      detailsEmpty.style.display = "none";
      topicMessages.innerHTML = `<div class="hint">loading ${esc(topicName)}...</div>`;
      try {
        const data = await apiGet(`/api/topic?name=${encodeURIComponent(topicName)}&limit=20`);
        const lines = [`topic: ${topicName}`, `messages: ${(data.messages || []).length}`];
        detailsPre.textContent = lines.join("\n");
        detailsPre.style.display = "block";
        topicMessages.innerHTML = (data.messages || []).map((m) => {
          return `<div class="topic-msg">`
            + `<div class="meta">${esc(fmtTime(m.created_at_iso || m.created_at))} · ${esc(m.id || "-")} · ${esc(m.author || "unknown")}</div>`
            + `<div class="body">${esc(m.body || m.summary || "")}</div>`
            + `</div>`;
        }).join("") || `<div class="hint">No messages.</div>`;
      } catch (err) {
        topicMessages.innerHTML = `<div class="hint">failed to load topic: ${esc(err.message || err)}</div>`;
      }
    }

    function attachHandlers() {
      for (const id of ["tab-btn-loops", "tab-btn-issues", "tab-btn-forum"]) {
        document.getElementById(id).addEventListener("click", () => {
          const tab = document.getElementById(id).getAttribute("data-tab");
          setActiveTab(tab || "loops");
        });
      }

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
        state.selectedIssue = null;
        document.getElementById("issue-selected").value = "";
        setActiveTab("loops");
        renderSessions(state.data || {});
        renderIssues(state.data || {});
        renderTopics(state.data || {});
        renderSessionDetail(state.selectedSession);
      });

      document.getElementById("issues-body").addEventListener("click", (ev) => {
        const row = ev.target.closest("tr[data-kind='issue']");
        if (!row) return;
        state.selectedIssue = row.getAttribute("data-id");
        state.selectedSession = null;
        state.selectedTopic = null;
        document.getElementById("issue-selected").value = state.selectedIssue || "";
        setActiveTab("issues");
        renderSessions(state.data || {});
        renderIssues(state.data || {});
        renderTopics(state.data || {});
        renderIssueDetail(state.selectedIssue);
      });

      document.getElementById("topics-body").addEventListener("click", (ev) => {
        const row = ev.target.closest("tr[data-kind='topic']");
        if (!row) return;
        state.selectedTopic = row.getAttribute("data-name");
        state.selectedSession = null;
        state.selectedIssue = null;
        document.getElementById("issue-selected").value = "";
        setActiveTab("forum");
        renderSessions(state.data || {});
        renderIssues(state.data || {});
        renderTopics(state.data || {});
        renderTopicDetail(state.selectedTopic);
      });

      document.getElementById("start-loop").addEventListener("click", async () => {
        const prompt = String(document.getElementById("start-prompt").value || "").trim();
        const program = String(document.getElementById("start-program").value || "").trim();
        const project = String(document.getElementById("start-project").value || "").trim();
        if (!prompt) {
          showActionStatus("prompt is required to start a loop", "warn");
          return;
        }
        try {
          const result = await apiPost("/api/loops/start", {
            prompt,
            program: program || null,
            project: project || null,
          });
          showActionStatus(`started ${result.session_id} (${result.program})`, "ok");
          state.selectedSession = result.session_id;
          state.selectedTopic = null;
          state.selectedIssue = null;
          document.getElementById("start-prompt").value = "";
          setActiveTab("loops");
          await tick();
        } catch (err) {
          showActionStatus(`failed to start loop: ${err.message || err}`, "err");
        }
      });

      async function sendControl(command, content) {
        if (!state.selectedSession) {
          showActionStatus("select a session first", "warn");
          return;
        }
        const author = String(document.getElementById("session-author").value || "").trim();
        try {
          await apiPost(`/api/loops/${encodeURIComponent(state.selectedSession)}/control`, {
            command,
            content: content || "",
            author: author || null,
          });
          showActionStatus(`${command} sent to ${state.selectedSession}`, "ok");
          await tick();
        } catch (err) {
          showActionStatus(`control failed: ${err.message || err}`, "err");
        }
      }

      document.getElementById("session-pause").addEventListener("click", async () => sendControl("pause", ""));
      document.getElementById("session-resume").addEventListener("click", async () => sendControl("resume", ""));
      document.getElementById("session-stop").addEventListener("click", async () => sendControl("stop", ""));
      document.getElementById("session-context-set").addEventListener("click", async () => {
        const content = String(document.getElementById("session-context").value || "").trim();
        await sendControl("context_set", content);
      });
      document.getElementById("session-context-clear").addEventListener("click", async () => {
        await sendControl("context_clear", "");
      });

      document.getElementById("issue-create").addEventListener("click", async () => {
        const title = String(document.getElementById("issue-title").value || "").trim();
        const tags = String(document.getElementById("issue-tags").value || "").trim();
        const priority = Number(document.getElementById("issue-priority").value || "3");
        if (!title) {
          showActionStatus("issue title is required", "warn");
          return;
        }
        try {
          const issue = await apiPost("/api/issues/create", {
            title,
            priority,
            tags,
          });
          document.getElementById("issue-title").value = "";
          document.getElementById("issue-tags").value = "";
          showActionStatus(`created issue ${issue.id}`, "ok");
          state.selectedIssue = issue.id;
          state.selectedSession = null;
          state.selectedTopic = null;
          document.getElementById("issue-selected").value = issue.id || "";
          setActiveTab("issues");
          await tick();
          await renderIssueDetail(issue.id);
        } catch (err) {
          showActionStatus(`issue create failed: ${err.message || err}`, "err");
        }
      });

      document.getElementById("issue-update").addEventListener("click", async () => {
        const issueId = String(document.getElementById("issue-selected").value || "").trim() || state.selectedIssue;
        if (!issueId) {
          showActionStatus("select an issue first", "warn");
          return;
        }
        const status = String(document.getElementById("issue-status").value || "").trim();
        const comment = String(document.getElementById("issue-comment").value || "").trim();
        try {
          await apiPost(`/api/issues/${encodeURIComponent(issueId)}/status`, { status });
          if (comment) {
            await apiPost(`/api/issues/${encodeURIComponent(issueId)}/comment`, { message: comment });
          }
          document.getElementById("issue-comment").value = "";
          showActionStatus(`updated issue ${issueId}`, "ok");
          state.selectedIssue = issueId;
          state.selectedSession = null;
          state.selectedTopic = null;
          setActiveTab("issues");
          await tick();
          await renderIssueDetail(issueId);
        } catch (err) {
          showActionStatus(`issue update failed: ${err.message || err}`, "err");
        }
      });

      document.getElementById("forum-post").addEventListener("click", async () => {
        const topic = String(document.getElementById("forum-topic").value || "").trim();
        const message = String(document.getElementById("forum-message").value || "").trim();
        const author = String(document.getElementById("forum-author").value || "").trim();
        if (!topic || !message) {
          showActionStatus("forum topic and message are required", "warn");
          return;
        }
        try {
          const row = await apiPost("/api/forum/post", {
            topic,
            message,
            author: author || null,
          });
          showActionStatus(`posted forum message ${row.id} to ${row.topic}`, "ok");
          document.getElementById("forum-message").value = "";
          state.selectedTopic = row.topic;
          state.selectedSession = null;
          state.selectedIssue = null;
          setActiveTab("forum");
          await tick();
          await renderTopicDetail(row.topic);
        } catch (err) {
          showActionStatus(`forum post failed: ${err.message || err}`, "err");
        }
      });
    }

    async function tick() {
      try {
        const data = await apiGet("/api/overview");
        state.data = data;
        applyMetrics(data);
        renderSessions(data);
        renderIssues(data);
        renderTopics(data);

        if (state.selectedSession) {
          renderSessionDetail(state.selectedSession);
        } else {
          resetLoopDetail();
        }
        if (state.selectedIssue) {
          await renderIssueDetail(state.selectedIssue);
        } else {
          resetIssueDetail();
        }
        if (state.selectedTopic) {
          await renderTopicDetail(state.selectedTopic);
        } else {
          resetForumDetail();
        }
        if (!state.selectedSession && !state.selectedIssue && !state.selectedTopic) {
          setSelectionStatus("none");
        }
      } catch (err) {
        document.getElementById("generated").textContent = `error: ${err.message || err}`;
        showActionStatus(`monitor refresh failed: ${err.message || err}`, "err");
      }
    }

    async function init() {
      attachHandlers();
      setActiveTab(state.activeTab);
      resetLoopDetail();
      resetIssueDetail();
      resetForumDetail();
      setSelectionStatus("none");
      try {
        state.meta = await apiGet("/api/meta");
        if (state.meta && state.meta.program && state.meta.program.name) {
          document.getElementById("start-program").value = state.meta.program.name;
        }
        if (state.meta && state.meta.program_error) {
          showActionStatus(`program config issue: ${state.meta.program_error}`, "warn");
        } else {
          showActionStatus("ready. choose a tab and start operating.", "ok");
        }
      } catch (err) {
        showActionStatus(`failed to load meta: ${err.message || err}`, "err");
      }
      await tick();
      setInterval(tick, REFRESH_MS);
    }

    init();
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


def _required_phases(program: ProgramFileConfig) -> list[str]:
    phases: list[str] = []
    for phase, _ in program.loop_steps:
        if phase not in phases:
            phases.append(phase)
    return phases


def _resolve_program(repo_root: Path, program_name: str | None) -> ProgramFileConfig:
    file_cfg = load_config(repo_root)
    program = file_cfg.program
    if program is None:
        raise ValueError(
            file_cfg.error
            or "missing or invalid .loopfarm/loopfarm.toml [program] configuration"
        )

    requested = (program_name or "").strip()
    if requested and requested != program.name:
        raise ValueError(
            f"program {requested!r} not found (configured: {program.name!r})"
        )
    return program


def _build_loop_config(
    *,
    repo_root: Path,
    prompt: str,
    program_name: str | None,
    project_name: str | None,
) -> tuple[LoopfarmConfig, ProgramFileConfig]:
    trimmed_prompt = prompt.strip()
    if not trimmed_prompt:
        raise ValueError("missing prompt")

    program = _resolve_program(repo_root, program_name)
    required_phases = _required_phases(program)

    phase_cli_overrides: list[tuple[str, str]] = []
    phase_prompt_overrides: list[tuple[str, str]] = []
    phase_injections: list[tuple[str, tuple[str, ...]]] = []
    phase_models: list[tuple[str, CodexPhaseModel]] = []

    for phase in required_phases:
        phase_cfg = program.phases.get(phase)
        if phase_cfg is None:
            raise ValueError(f"missing [program.phase.{phase}] configuration")

        prompt_path = (phase_cfg.prompt or "").strip()
        if not prompt_path:
            raise ValueError(
                f"missing prompt for phase {phase!r} in [program.phase.{phase}]"
            )

        phase_cli = (phase_cfg.cli or "").strip()
        if not phase_cli:
            raise ValueError(f"missing cli for phase {phase!r} in [program.phase.{phase}]")

        phase_model = (phase_cfg.model or "").strip()
        if phase_cli != "kimi" and not phase_model:
            raise ValueError(
                f"missing model for phase {phase!r} in [program.phase.{phase}]"
            )

        prompt_file = Path(prompt_path)
        if not prompt_file.is_absolute():
            prompt_file = repo_root / prompt_file
        if not prompt_file.exists() or not prompt_file.is_file():
            raise ValueError(f"prompt file not found: {prompt_path} (phase: {phase})")

        phase_prompt_overrides.append((phase, prompt_path))
        phase_cli_overrides.append((phase, phase_cli))
        if phase_cfg.inject:
            phase_injections.append((phase, phase_cfg.inject))
        if phase_model:
            reasoning = (phase_cfg.reasoning or "xhigh").strip() or "xhigh"
            phase_models.append((phase, CodexPhaseModel(phase_model, reasoning)))

    project = (project_name or program.project or repo_root.name).strip() or repo_root.name
    cfg = LoopfarmConfig(
        repo_root=repo_root,
        project=str(project),
        prompt=trimmed_prompt,
        loop_steps=program.loop_steps,
        termination_phase=program.termination_phase,
        loop_report_source_phase=program.report_source_phase,
        loop_report_target_phases=program.report_target_phases,
        phase_models=tuple(phase_models),
        phase_cli_overrides=tuple(phase_cli_overrides),
        phase_prompt_overrides=tuple(phase_prompt_overrides),
        phase_injections=tuple(phase_injections),
    )
    return cfg, program


class LoopLauncher:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def start(
        self,
        *,
        prompt: str,
        program_name: str | None,
        project_name: str | None,
    ) -> dict[str, Any]:
        cfg, program = _build_loop_config(
            repo_root=self.repo_root,
            prompt=prompt,
            program_name=program_name,
            project_name=project_name,
        )
        session_id = new_session_id()

        def _target() -> None:
            try:
                run_loop(cfg, session_id=session_id)
            finally:
                with self._lock:
                    self._threads.pop(session_id, None)

        thread = threading.Thread(
            target=_target,
            name=f"loopfarm-session-{session_id}",
            daemon=True,
        )
        with self._lock:
            self._threads[session_id] = thread
        thread.start()

        return {
            "session_id": session_id,
            "program": program.name,
            "project": cfg.project,
            "status": "running",
            "started_at": utc_now_iso(),
        }


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
        self.session_store = SessionStore(self.forum)

    def _forum_topics(self) -> list[dict[str, Any]]:
        return self.forum.list_topics()

    def _forum_read(self, topic: str, *, limit: int) -> list[dict[str, Any]]:
        return self.forum.read(topic, limit=limit)

    def _issue_list(self, status: str) -> list[dict[str, Any]]:
        return self.issue.list(status=status, limit=1000)

    def create_issue(
        self,
        *,
        title: str,
        body: str = "",
        status: str = "open",
        priority: int = 3,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.issue.create(
            title=title,
            body=body,
            status=status,
            priority=priority,
            tags=tags or [],
        )

    def set_issue_status(self, issue_id: str, status: str) -> dict[str, Any]:
        return self.issue.set_status(issue_id, status)

    def get_issue(self, issue_id: str) -> dict[str, Any] | None:
        return self.issue.show(issue_id)

    def add_issue_comment(
        self, issue_id: str, message: str, *, author: str | None
    ) -> dict[str, Any]:
        return self.issue.add_comment(issue_id, message, author=author)

    def post_forum(
        self, topic: str, message: str, *, author: str | None
    ) -> dict[str, Any]:
        return self.forum.post(topic, message, author=author)

    def apply_control(
        self,
        session_id: str,
        *,
        command: str,
        content: str | None,
        author: str | None,
    ) -> dict[str, Any]:
        cmd = command.strip().lower()
        status_by_command = {
            "pause": "paused",
            "resume": "running",
            "stop": "stopped",
            "context_set": "running",
            "context_clear": "running",
        }
        if cmd not in status_by_command:
            raise ValueError(
                "invalid control command (expected: pause, resume, stop, context_set, context_clear)"
            )

        msg = (content or "").strip()
        if cmd == "context_set" and not msg:
            raise ValueError("content is required for context_set")

        meta = self.session_store.get_session_meta(session_id) or {}
        phase = str(meta.get("phase") or "").strip() or None
        iteration = _to_int(meta.get("iteration"))
        return self.session_store.set_control_state(
            session_id,
            status=status_by_command[cmd],
            command=cmd,
            phase=phase,
            iteration=iteration,
            author=(author or "").strip() or "monitor",
            content=msg or None,
        )

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
                    "author": message.get("author"),
                    "created_at": created_at,
                    "created_at_iso": _iso_from_epoch_ms(created_at),
                    "summary": summary,
                    "body": str(body or ""),
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

    def invalidate(self) -> None:
        with self._lock:
            self._snapshot = None
            self._stamp = 0.0


class MonitorHandler(BaseHTTPRequestHandler):
    collector: MonitorCollector
    cache: SnapshotCache
    launcher: LoopLauncher
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
        if path == "/api/meta":
            try:
                program = _resolve_program(self.collector.repo_root, None)
                program_payload: dict[str, Any] | None = {
                    "name": program.name,
                    "project": program.project,
                    "steps": [[phase, repeat] for phase, repeat in program.loop_steps],
                    "termination_phase": program.termination_phase,
                    "report_source_phase": program.report_source_phase,
                    "report_target_phases": list(program.report_target_phases),
                }
                program_error = None
            except ValueError as exc:
                program_payload = None
                program_error = str(exc)

            self._send_json(
                200,
                {
                    "issue_statuses": list(ISSUE_STATUSES),
                    "control_commands": [
                        "pause",
                        "resume",
                        "stop",
                        "context_set",
                        "context_clear",
                    ],
                    "program": program_payload,
                    "program_error": program_error,
                },
            )
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
        issue_match = re.match(r"^/api/issues/(?P<issue_id>[^/]+)$", path)
        if issue_match:
            issue_id = unquote(issue_match.group("issue_id"))
            row = self.collector.get_issue(issue_id)
            if row is None:
                self._send_json(404, {"error": f"issue not found: {issue_id}"})
                return
            self._send_json(200, row)
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        try:
            if path == "/api/loops/start":
                prompt = str(payload.get("prompt") or "").strip()
                program_name = payload.get("program")
                if program_name is not None:
                    program_name = str(program_name)
                project_name = payload.get("project")
                if project_name is not None:
                    project_name = str(project_name)
                data = self.launcher.start(
                    prompt=prompt,
                    program_name=program_name,
                    project_name=project_name,
                )
                self.cache.invalidate()
                self._send_json(200, data)
                return

            control_match = re.match(r"^/api/loops/(?P<session_id>[^/]+)/control$", path)
            if control_match:
                session_id = unquote(control_match.group("session_id"))
                command = str(payload.get("command") or "").strip()
                content = payload.get("content")
                if content is not None:
                    content = str(content)
                author = payload.get("author")
                if author is not None:
                    author = str(author)
                data = self.collector.apply_control(
                    session_id,
                    command=command,
                    content=content,
                    author=author,
                )
                self.cache.invalidate()
                self._send_json(200, {"ok": True, "session_id": session_id, "control": data})
                return

            if path == "/api/issues/create":
                title = str(payload.get("title") or "").strip()
                body = str(payload.get("body") or "")
                status = str(payload.get("status") or "open").strip() or "open"
                priority = _to_int(payload.get("priority"))
                tags_raw = payload.get("tags")
                tags: list[str] = []
                if isinstance(tags_raw, list):
                    for item in tags_raw:
                        text = str(item).strip()
                        if text:
                            tags.append(text)
                elif isinstance(tags_raw, str):
                    for item in tags_raw.split(","):
                        text = item.strip()
                        if text:
                            tags.append(text)
                row = self.collector.create_issue(
                    title=title,
                    body=body,
                    status=status,
                    priority=priority if priority is not None else 3,
                    tags=tags,
                )
                self.cache.invalidate()
                self._send_json(200, row)
                return

            issue_status_match = re.match(r"^/api/issues/(?P<issue_id>[^/]+)/status$", path)
            if issue_status_match:
                issue_id = unquote(issue_status_match.group("issue_id"))
                status = str(payload.get("status") or "").strip()
                row = self.collector.set_issue_status(issue_id, status)
                self.cache.invalidate()
                self._send_json(200, row)
                return

            issue_comment_match = re.match(r"^/api/issues/(?P<issue_id>[^/]+)/comment$", path)
            if issue_comment_match:
                issue_id = unquote(issue_comment_match.group("issue_id"))
                message = str(payload.get("message") or "").strip()
                author = payload.get("author")
                if author is not None:
                    author = str(author)
                row = self.collector.add_issue_comment(issue_id, message, author=author)
                self._send_json(200, row)
                return

            if path == "/api/forum/post":
                topic = str(payload.get("topic") or "").strip()
                message = str(payload.get("message") or "").strip()
                author = payload.get("author")
                if author is not None:
                    author = str(author)
                row = self.collector.post_forum(topic, message, author=author)
                self.cache.invalidate()
                self._send_json(200, row)
                return
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except Exception as exc:
            self._send_json(500, {"error": f"internal error: {exc}"})
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

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict[str, Any]:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            return {}
        try:
            length = max(0, int(raw_len))
        except ValueError:
            raise ValueError("invalid Content-Length header")
        if length == 0:
            return {}
        data = self.rfile.read(length)
        if not data:
            return {}
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload


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
    collector: MonitorCollector,
    cache: SnapshotCache,
    refresh_seconds: int,
    launcher: LoopLauncher,
) -> type[MonitorHandler]:
    class _Handler(MonitorHandler):
        pass

    _Handler.collector = collector
    _Handler.cache = cache
    _Handler.refresh_seconds = refresh_seconds
    _Handler.launcher = launcher
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
    launcher = LoopLauncher(cfg.repo_root)
    cache = SnapshotCache(
        collector,
        ttl_seconds=cfg.cache_ttl_seconds,
        max_sessions=cfg.max_sessions,
        max_issues=cfg.max_issues,
        max_topics=cfg.max_topics,
    )

    handler_cls = _make_handler(
        collector,
        cache,
        cfg.refresh_seconds,
        launcher,
    )
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
