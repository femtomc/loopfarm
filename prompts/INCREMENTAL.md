# Incremental Backward Pass Protocol

Backward passes should be **incremental** - only re-analyzing what's changed
since the last audit. This avoids redundant token consumption.

## synth-forum Topic Schema

| Topic                           | Purpose                       | TTL    |
| ------------------------------- | ----------------------------- | ------ |
| `backward:state:<project>`      | Last audit commit + timestamp | None   |
| `backward:findings:<project>`   | Findings by category          | None   |
| `backward:literature:<project>` | Cached search results         | 7 days |
| `loopfarm:forward:<session>`       | Forward pass report           | None   |

### State Message Format

```json
{
  "commit": "abc123",
  "timestamp": "2026-01-17T12:00:00Z",
  "categories_audited": ["ffi", "storage", "protocol"],
  "files_audited": ["src/foo.zig", "src/bar.zig"]
}
```

### Findings Message Format

```json
{
  "category": "ffi",
  "commit": "abc123",
  "findings": [
    {
      "file": "src/ffi.zig",
      "line": 42,
      "issue": "Missing null check",
      "severity": "medium"
    },
    {
      "file": "src/ffi.zig",
      "line": 87,
      "issue": "Resource leak on error path",
      "severity": "high"
    }
  ],
  "issues_filed": ["workshop-abc123"]
}
```

### Literature Cache Format

```json
{
  "query": "code chunking semantic embeddings",
  "query_hash": "a1b2c3",
  "timestamp": "2026-01-17T12:00:00Z",
  "ttl_days": 7,
  "results": [
    {
      "title": "Paper Title",
      "authors": "...",
      "year": 2024,
      "citations": 150,
      "relevance": "high"
    }
  ],
  "actions_taken": ["Filed issue workshop-xyz for technique X"]
}
```

### Forward Report Format

```json
{
  "timestamp": "2026-01-23T12:00:00Z",
  "session": "loopfarm-abcdef12",
  "pre_head": "abc123...",
  "post_head": "def456...",
  "head_changed": true,
  "commit_range": "abc123..def456",
  "commits": ["def456 Fix runner forward report"],
  "diffstat": ["loopfarm/src/loopfarm/runner.py | 120 ++++++----"],
  "name_status": ["M loopfarm/src/loopfarm/runner.py"],
  "dirty": false,
  "status": [],
  "staged_diffstat": [],
  "unstaged_diffstat": [],
  "staged_name_status": [],
  "unstaged_name_status": [],
  "summary": "Added forward pass reporting and injected it into backward prompts."
}
```

## Invalidation Rules

### Code Audit Invalidation

A category needs re-audit when:

1. **Files changed**: `git diff <last-commit>..HEAD` includes files relevant to
   that category
2. **Never audited**: Category not in `categories_audited`
3. **Force refresh**: User explicitly requests full audit

Category-to-file mapping (example for chunkworm):

| Category | Files                                 |
| -------- | ------------------------------------- |
| ffi      | `src/ffi/*.zig`, `build.zig` (C deps) |
| storage  | `src/db.zig`, `src/schema.zig`        |
| chunking | `src/chunker.zig`, `src/ast.zig`      |
| http     | `src/http.zig`, `src/providers/*.zig` |
| protocol | `src/mcp.zig`, `src/jsonrpc.zig`      |

### Literature Invalidation

A search needs refresh when:

1. **TTL expired**: `timestamp + ttl_days < now`
2. **Related code changed**: Files in relevant category changed
3. **Never searched**: Query not in cache
4. **Force refresh**: User explicitly requests

## Backward Prompt Template

```markdown

## Working Directory

\`\`\`bash cd <project> \`\`\`

## Pre-Audit Check

Before auditing, determine what needs re-analysis.

### 1. Read Last Audit State

\`\`\`bash synth-forum read backward:state:<project> --limit 1 \`\`\`

If no state exists, this is a **full audit** - proceed to all categories.

### 2. Check for Changes

\`\`\`bash git log --oneline <last-commit>..HEAD git diff <last-commit>..HEAD
--name-only \`\`\`

### 3. Determine Scope

- **No changes**: Skip to Issue Triage (section 7)
- **Changes in category X**: Re-audit category X only
- **New files**: Determine which category, audit those

Report scope before proceeding:

> **Audit scope**: Categories [X, Y] invalidated by changes to [file1, file2]

## Scoped Audit Tasks

Only perform tasks for invalidated categories.

### 1. FFI Correctness (if invalidated)

...

### 2. Algorithm Quality (if invalidated)

...

[etc - same content as before, but conditional]

## Literature Search

### 1. Check Cache

\`\`\`bash synth-forum read backward:literature:<project> --limit 10 \`\`\`

### 2. Skip Fresh Searches

If a query was run within TTL and no related files changed, skip it.

### 3. Run New/Stale Searches

Only search for:

- Topics never searched
- Topics with expired TTL
- Topics where related code changed

### 4. Update Cache

\`\`\`bash synth-forum post backward:literature:<project> -m '<json>' \`\`\`

## Issue Triage

[Always run - lightweight]

## Post-Audit Update

After completing audit:

\`\`\`bash synth-forum post backward:state:<project> -m '{ "commit": "<current-HEAD>",
"timestamp": "<now>", "categories_audited": [...], "files_audited": [...] }'
\`\`\`

\`\`\`bash synth-forum post backward:findings:<project> -m '<findings-json>' \`\`\`
```

## Future: Semantic Search Integration

When semantic search tooling is available, enhance with semantic queries to
enable smarter invalidation than file-path matching alone.
