import type { Issue } from "./types";

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

