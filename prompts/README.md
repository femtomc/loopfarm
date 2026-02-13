# Prompts

Loopfarm prompt surfaces are Markdown templates rendered at runtime.

Minimal-core orchestration treats exactly two files as user-authored "code":

- `.loopfarm/orchestrator.md` (planning/decomposition prompt)
- `.loopfarm/roles/*.md` (atomic execution role prompts)

Run `loopfarm init` to scaffold these surfaces.

## Template Placeholders

Replaced during template rendering:

- `{{PROMPT}}`: the current issue prompt payload (title/body)
- `{{SESSION}}`: the active loop session id
- `{{PROJECT}}`: the project label (defaults from repo/team)

Context injection placeholders (optional):

- `{{DYNAMIC_CONTEXT}}`: combined session + operator context block
- `{{SESSION_CONTEXT}}`: session-only context block
- `{{USER_CONTEXT}}`: operator-only context block

Additional runtime injections (optional):

- `{{PHASE_BRIEFING}}`: recent per-phase summaries (when enabled)
- `{{FORWARD_REPORT}}`: forward-pass report payload (when enabled)

## Includes

Templates can include other Markdown files via:

```text
{{> relative/path.md}}
```

Includes are resolved relative to the including file.

## CLI Quick Start

```bash
loopfarm init
loopfarm "Design and implement sync engine"
loopfarm docs show issue-dag-orchestration --output rich
```
