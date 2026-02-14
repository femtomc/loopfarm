import type { EventRecord, Issue } from "./types";

function escapeHtml(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fmtEpochSeconds(sec: number | undefined): string {
  if (!sec || !Number.isFinite(sec)) return "";
  try {
    return new Date(sec * 1000).toISOString().slice(0, 19).replace("T", " ") + "Z";
  } catch {
    return String(sec);
  }
}

export function renderIssuesPage(params: { storeRoot: string; issues: Issue[] }): string {
  const { storeRoot, issues } = params;

  const rows = issues
    .map((issue) => {
      const id = escapeHtml(issue.id);
      const title = escapeHtml(issue.title ?? "");
      const status = escapeHtml(issue.status ?? "");
      const prio = issue.priority ?? "";
      const updated = fmtEpochSeconds(issue.updated_at ?? issue.created_at);
      const tags = Array.isArray(issue.tags) ? escapeHtml(issue.tags.join(",")) : "";
      return [
        "<tr>",
        `<td class="id"><a href="/api/issues/${encodeURIComponent(issue.id)}">${id}</a></td>`,
        `<td class="events"><a href="/events?issue_id=${encodeURIComponent(issue.id)}">events</a></td>`,
        `<td class="status">${status}</td>`,
        `<td class="prio">${prio}</td>`,
        `<td class="updated">${escapeHtml(updated)}</td>`,
        `<td class="tags">${tags}</td>`,
        `<td class="title">${title}</td>`,
        "</tr>",
      ].join("");
    })
    .join("\n");

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Inshallah Monitor</title>
    <style>
      :root {
        color-scheme: light;
        --fg: #111;
        --muted: #666;
        --bg: #fff;
        --border: #ddd;
        --link: #0b57d0;
      }
      body {
        margin: 0;
        padding: 16px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono",
          "Courier New", monospace;
        font-size: 12px;
        line-height: 1.25;
        background: var(--bg);
        color: var(--fg);
      }
      header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 12px;
      }
      h1 {
        font-size: 14px;
        margin: 0;
      }
      .meta {
        color: var(--muted);
      }
      a { color: var(--link); text-decoration: none; }
      a:hover { text-decoration: underline; }
      table {
        width: 100%;
        border-collapse: collapse;
      }
      thead th {
        position: sticky;
        top: 0;
        background: var(--bg);
        border-bottom: 1px solid var(--border);
        text-align: left;
        padding: 6px 8px;
        white-space: nowrap;
      }
      tbody td {
        border-bottom: 1px solid var(--border);
        padding: 4px 8px;
        vertical-align: top;
      }
      td.id { white-space: nowrap; }
      td.events { white-space: nowrap; }
      td.status { white-space: nowrap; color: var(--muted); }
      td.prio { white-space: nowrap; color: var(--muted); }
      td.updated { white-space: nowrap; color: var(--muted); }
      td.tags { white-space: nowrap; color: var(--muted); }
      td.title { width: 100%; }
    </style>
  </head>
  <body>
    <header>
      <h1>Inshallah Monitor</h1>
      <div class="meta">
        store_root=${escapeHtml(storeRoot)} | issues=${issues.length} |
        <a href="/api/issues">/api/issues</a>
      </div>
    </header>
    <table>
      <thead>
        <tr>
          <th>id</th>
          <th>events</th>
          <th>status</th>
          <th>prio</th>
          <th>updated</th>
          <th>tags</th>
          <th>title</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  </body>
</html>`;
}

function safeQueryString(params: Record<string, string | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "") continue;
    sp.set(k, v);
  }
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

function previewEvent(e: EventRecord): string {
  if (e.type === "raw") {
    return typeof e.value === "string" ? e.value : String(e.value);
  }

  const v = e.value;
  if (!v || typeof v !== "object" || Array.isArray(v)) return JSON.stringify(v) ?? "";

  if (e.type === "thread.started") {
    const tid = (v as { thread_id?: unknown }).thread_id;
    if (typeof tid === "string") return `thread_id=${tid}`;
  }

  if (e.type.startsWith("item.")) {
    const item = (v as { item?: unknown }).item;
    if (item && typeof item === "object" && !Array.isArray(item)) {
      const id = typeof (item as { id?: unknown }).id === "string" ? (item as { id: string }).id : "";
      const t = typeof (item as { type?: unknown }).type === "string" ? (item as { type: string }).type : "";
      const cmd =
        t === "command_execution" && typeof (item as { command?: unknown }).command === "string"
          ? (item as { command: string }).command
          : "";
      const txt =
        (t === "agent_message" || t === "reasoning") && typeof (item as { text?: unknown }).text === "string"
          ? (item as { text: string }).text
          : "";
      const bits = [
        id ? `item.id=${id}` : "",
        t ? `item.type=${t}` : "",
        cmd ? `cmd=${cmd}` : "",
        txt ? `text=${txt}` : "",
      ].filter(Boolean);
      if (bits.length) return bits.join(" ");
    }
  }

  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

function truncate(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + "...(truncated)";
}

export function renderEventsPage(params: {
  storeRoot: string;
  query: { issue_id?: string; run_id?: string; type?: string; limit?: number };
  events: EventRecord[];
}): string {
  const issue_id = params.query.issue_id ?? "";
  const run_id = params.query.run_id ?? "";
  const type = params.query.type ?? "";
  const limit = params.query.limit ?? 200;

  const apiHref =
    "/api/events" +
    safeQueryString({
      issue_id: issue_id || undefined,
      run_id: run_id || undefined,
      type: type || undefined,
      limit: String(limit),
    });

  const rows = params.events
    .map((e, idx) => {
      const preview = truncate(previewEvent(e), 400);
      const run = e.run_id ?? "";
      const src = escapeHtml(`${e.source}:${e.line}`);
      const err = e.parse_error ? ` parse_error=${e.parse_error}` : "";
      return [
        "<tr>",
        `<td class="seq">${idx + 1}</td>`,
        `<td class="run">${escapeHtml(run)}</td>`,
        `<td class="type">${escapeHtml(e.type)}</td>`,
        `<td class="src">${src}</td>`,
        `<td class="preview"><pre>${escapeHtml(preview + err)}</pre></td>`,
        "</tr>",
      ].join("");
    })
    .join("\n");

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Inshallah Monitor - Events</title>
    <style>
      :root {
        color-scheme: light;
        --fg: #111;
        --muted: #666;
        --bg: #fff;
        --border: #ddd;
        --link: #0b57d0;
      }
      body {
        margin: 0;
        padding: 16px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono",
          "Courier New", monospace;
        font-size: 12px;
        line-height: 1.25;
        background: var(--bg);
        color: var(--fg);
      }
      header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 12px;
      }
      h1 { font-size: 14px; margin: 0; }
      .meta { color: var(--muted); }
      a { color: var(--link); text-decoration: none; }
      a:hover { text-decoration: underline; }
      form {
        display: flex;
        flex-wrap: wrap;
        gap: 8px 12px;
        align-items: end;
        border: 1px solid var(--border);
        padding: 8px;
        margin-bottom: 12px;
      }
      label { display: flex; flex-direction: column; gap: 2px; }
      input {
        font: inherit;
        padding: 4px 6px;
        border: 1px solid var(--border);
        border-radius: 4px;
        min-width: 220px;
      }
      input.small { min-width: 140px; }
      button {
        font: inherit;
        padding: 4px 10px;
        border: 1px solid var(--border);
        border-radius: 4px;
        background: var(--bg);
        cursor: pointer;
      }
      table { width: 100%; border-collapse: collapse; }
      thead th {
        position: sticky;
        top: 0;
        background: var(--bg);
        border-bottom: 1px solid var(--border);
        text-align: left;
        padding: 6px 8px;
        white-space: nowrap;
      }
      tbody td {
        border-bottom: 1px solid var(--border);
        padding: 4px 8px;
        vertical-align: top;
      }
      td.seq { white-space: nowrap; color: var(--muted); }
      td.run { white-space: nowrap; color: var(--muted); }
      td.type { white-space: nowrap; }
      td.src { white-space: nowrap; color: var(--muted); }
      td.preview { width: 100%; }
      td.preview pre {
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
      }
    </style>
  </head>
  <body>
    <header>
      <h1><a href="/issues">Inshallah Monitor</a> / Events</h1>
      <div class="meta">
        store_root=${escapeHtml(params.storeRoot)} | events=${params.events.length} |
        <a href="${escapeHtml(apiHref)}">/api/events</a>
      </div>
    </header>

    <form method="GET" action="/events">
      <label>issue_id
        <input name="issue_id" value="${escapeHtml(issue_id)}" placeholder="inshallah-..." />
      </label>
      <label>run_id
        <input class="small" name="run_id" value="${escapeHtml(run_id)}" placeholder="thread_id" />
      </label>
      <label>type
        <input class="small" name="type" value="${escapeHtml(type)}" placeholder="item.completed" />
      </label>
      <label>limit
        <input class="small" name="limit" value="${escapeHtml(String(limit))}" />
      </label>
      <button type="submit">Filter</button>
      <div class="meta" style="align-self:center">
        <a href="/issues">back to issues</a>
      </div>
    </form>

    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>run_id</th>
          <th>type</th>
          <th>source</th>
          <th>preview</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  </body>
</html>`;
}
