# Prompts

Generic templates for autonomous development sessions.

## Usage

```bash
# Work on existing issues
loopfarm qed

# Skip planning, then work
loopfarm --skip-plan qed

# Codex CLI runner
loopfarm --codex qed
```

`loopfarm` is implemented as a Python tool managed by `uv` (see `loopfarm/`).
Output is formatted by default in both Claude and Codex modes.

By default, loopfarm runs in `--mode implementation`: planning once, then the loop
`forward -> documentation -> architecture -> backward` (repeat). Use
`--skip-plan` to skip the initial planning phase.

`--mode research` is a separate pre-implementation loop for deep research and
issue/context curation.

Use `--phase-plan` in implementation mode to customize structure. Example:

```bash
loopfarm --mode implementation --phase-plan "planning,forward*5,documentation,architecture,backward" "Improve QED loop"
```

Research mode example:

```bash
loopfarm --mode research --phase-plan "planning,research*3,curation,backward" "Survey production actor runtimes"
```

`--loop` is still accepted as a legacy alias for `--phase-plan`.

## Programmatic API (run_loop)

You can drive the loopfarm loop from another process (e.g. a TUI) via
`loopfarm.run_loop` and consume structured events.

```python
from pathlib import Path

from loopfarm import LoopfarmConfig, LoopfarmEvent, LoopfarmIO, run_loop
from loopfarm.runner import CodexPhaseModel


def on_event(ev: LoopfarmEvent) -> None:
    # ev.type examples: session.start, phase.start, phase.end, stream.text, session.end
    # stream.* events include phase/iteration and are enriched with session_id in payload.
    print(f"[{ev.type}] phase={ev.phase} iter={ev.iteration} payload={ev.payload}")


cfg = LoopfarmConfig(
    repo_root=Path.cwd(),
    cli="codex",
    model_override=None,
    skip_plan=True,
    project="workshop",
    prompt="Improve uwu harness",
    code_model=CodexPhaseModel(model="gpt-5.3-codex", reasoning="xhigh"),
    plan_model=CodexPhaseModel(model="gpt-5.2", reasoning="xhigh"),
    review_model=CodexPhaseModel(model="gpt-5.2", reasoning="xhigh"),
)

io = LoopfarmIO()  # or LoopfarmIO(stdout=io.StringIO(), stderr=io.StringIO())
exit_code = run_loop(cfg, session_id="loopfarm-demo", event_sink=on_event, io=io)
```

### Event contract

- `event_sink` receives `LoopfarmEvent` with `type`, `timestamp`, `phase`,
  `iteration`, and a `payload` dict.
- Phase-level events: `session.start`, `phase.start`, `phase.end`,
  `phase.error`, `phase.skip`, `session.complete`, `session.end`.
- Stream events from backends are forwarded as `stream.*` (e.g. `stream.text`,
  `stream.tool`, `stream.command.start`, `stream.command.end`, `stream.usage`).
  These include `phase`, `iteration`, and the `session_id` in `payload`.

### Custom backends and IO

- Pass a `backend_provider` to `run_loop` to supply a custom backend without
  shelling out. Signature: `(cli_name, phase, cfg) -> Backend`.
- Use `LoopfarmIO(stdout=..., stderr=...)` to capture backend output.

### Caveats

- The runner mutates `LOOPFARM_SESSION` and `DISCORD_THREAD_ID` in `os.environ`
  (legacy `LOOPFARM_SESSION` is also set for compatibility).
- Each phase writes temporary output/last-message files and deletes them after
  extraction.
- Prompts are loaded from `repo_root/loopfarm/prompts/`, and synth-forum is used for
  session metadata and forward reports.

## Loop Structure (Implementation Mode)

Reference contract: `loopfarm/docs/implementation-state-machine.md`

```
┌─────────────────────────────────────────────────────────┐
│  PLANNING (unless --skip-plan)                          │
│  - Explore codebase, understand current state           │
│  - Break down work into discrete issues                 │
│  - File issues with synth-issue                              │
├─────────────────────────────────────────────────────────┤
│  FORWARD PASS                                           │
│  - Pick ONE ready leaf issue (not parent/epic)          │
│  - Implement, test, commit                              │
├─────────────────────────────────────────────────────────┤
│  DOCUMENTATION PASS (Review-only)                       │
│  - Update docs/prose for current implementation cycle   │
│  - Coordinate doc work via synth-issue                  │
├─────────────────────────────────────────────────────────┤
│  ARCHITECTURE/PERFORMANCE PASS (Review-only)            │
│  - Review modularity and performance concerns           │
│  - Add findings/issues to the implementation epic       │
├─────────────────────────────────────────────────────────┤
│  BACKWARD PASS (Read-only)                              │
│  - Audit the codebase                                   │
│  - Integrate documentation/architecture findings        │
│  - File issues for findings                             │
│  - Search literature when relevant                      │
│  - Record state to synth-forum                                  │
│  - Read the injected Forward Pass Report (git summary)  │
│  - Sole termination gate (COMPLETE decision)            │
└─────────────────────────────────────────────────────────┘
         ↓ repeat until no issues remain
```

## Loop Structure (Research Mode)

```
┌─────────────────────────────────────────────────────────┐
│  PLANNING (unless --skip-plan)                          │
│  - Define research scope + hypotheses                   │
│  - Set up issue/forum structure                         │
├─────────────────────────────────────────────────────────┤
│  RESEARCH PASS                                          │
│  - Deep research: Vecky, web, papers, production code  │
│  - Capture findings to synth-forum                      │
├─────────────────────────────────────────────────────────┤
│  CURATION PASS                                          │
│  - Organize findings into actionable synth-issue graph  │
│  - Prepare implementation-ready backlog                 │
├─────────────────────────────────────────────────────────┤
│  BACKWARD / REPLANNING GATE                             │
│  - Validate readiness and remaining gaps                │
│  - Sole termination gate (COMPLETE decision)            │
└─────────────────────────────────────────────────────────┘
         ↓ repeat until research prep is complete
```

## Templates

| File          | Purpose                                  |
| ------------- | ---------------------------------------- |
| `writing.md`  | Style/rules for writing mode sessions    |
| `implementation/forward.md`  | Pick an issue, implement it, close it    |
| `implementation/documentation.md` | Documentation-only sync pass         |
| `implementation/architecture.md` | Architecture/performance review pass   |
| `implementation/backward.md` | Audit the codebase, file issues for work |
| `implementation/planning.md` | Break down work into issues (default)    |
| `research/*.md` | Mode-specific research/curation prompts |

Placeholders: `{{PROMPT}}`, `{{SESSION}}`, `{{PROJECT}}`, `{{FORWARD_REPORT}}`,
and `{{DYNAMIC_CONTEXT}}` are replaced at runtime. `{{SESSION_CONTEXT}}` and
`{{DISCORD_USER_CONTEXT}}` are optional split placeholders for session-level
and per-phase Discord guidance.

Prompt resolution is mode-aware: loopfarm checks in this order:

1. `prompts/<mode>/<phase>.md`
2. `prompts/implementation/<phase>.md`
3. `prompts/<phase>.md` (legacy fallback)

During documentation/architecture/backward phases, loopfarm injects a
**Forward Pass Report** (from
`loopfarm:forward:<session>` in synth-forum) that summarizes the immediately preceding
forward changes, so reviewers can scope their audit.

When running `loopfarm --mode writing`, loopfarm uses the same phase templates and
injects an explicit writing-mode section that points to `writing.md`.

## Codex Mode

When running `loopfarm --codex`, loopfarm uses the same templates listed above.
These templates include the required summary markers that Codex uses for phase
summary extraction.

Default Codex models:

- **FORWARD (coding/implementation):** `gpt-5.3-codex` with `reasoning=xhigh`
- **PLANNING + BACKWARD (planning/review):** `gpt-5.2` with `reasoning=xhigh`
- **RESEARCH + CURATION (research mode):** `gpt-5.2` with `reasoning=xhigh`
- **ARCHITECTURE (review):** `gpt-5.2` with `reasoning=xhigh`
- **DOCUMENTATION (default backend):** `gemini` with model `gemini-3-pro-preview`

Override with:

- `LOOPFARM_CODE_MODEL`, `LOOPFARM_PLAN_MODEL`, `LOOPFARM_REVIEW_MODEL`, `LOOPFARM_ARCHITECTURE_MODEL`, `LOOPFARM_DOCUMENTATION_MODEL`
- `LOOPFARM_CODE_REASONING`, `LOOPFARM_PLAN_REASONING`, `LOOPFARM_REVIEW_REASONING`, `LOOPFARM_ARCHITECTURE_REASONING`
- `LOOPFARM_IMPLEMENTATION_LOOP`, `LOOPFARM_RESEARCH_LOOP`

## Available Projects

Any package in the monorepo:

- **core/**: synth-forum, synth-issue, vecky, termcat, drawl, claudez, bibval,
  chunkworm, marketplace
- **lang/**: synth, laser, absynthe
- **research/**: qed, pluckz, fizz
