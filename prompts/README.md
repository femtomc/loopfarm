# Prompts

`loopfarm` runs strict program specs from `.loopfarm/loopfarm.toml` and/or `.loopfarm/programs/*.toml`.

## Program Contract

Required fields:

1. `[program].name`
2. `[program].steps`
3. `[program].termination_phase`
4. `[program.phase.<name>].cli`
5. `[program.phase.<name>].prompt`
6. `[program.phase.<name>].model` for non-`kimi` phases

Optional fields:

1. `[program].project`
2. `[program].report_source_phase`
3. `[program].report_target_phases`
4. `[program.phase.<name>].reasoning`
5. `[program.phase.<name>].inject`

## Example

```toml
[program]
name = "implementation"
project = "loopfarm"
steps = ["planning", "forward*5", "documentation", "architecture", "backward"]
termination_phase = "backward"
report_source_phase = "forward"
report_target_phases = ["documentation", "architecture", "backward"]

[program.phase.planning]
cli = "codex"
prompt = ".loopfarm/prompts/implementation/planning.md"
model = "gpt-5.2"
reasoning = "xhigh"

[program.phase.forward]
cli = "codex"
prompt = ".loopfarm/prompts/implementation/forward.md"
model = "gpt-5.3-codex"
reasoning = "xhigh"
inject = ["phase_briefing"]

[program.phase.documentation]
cli = "gemini"
prompt = ".loopfarm/prompts/implementation/documentation.md"
model = "gemini-3-pro-preview"

[program.phase.architecture]
cli = "codex"
prompt = ".loopfarm/prompts/implementation/architecture.md"
model = "gpt-5.2"
reasoning = "xhigh"
inject = ["forward_report"]

[program.phase.backward]
cli = "codex"
prompt = ".loopfarm/prompts/implementation/backward.md"
model = "gpt-5.2"
reasoning = "xhigh"
inject = ["forward_report"]
```

## Step Syntax

- `planning` may appear once at the beginning.
- Repeat uses `*N`, e.g. `forward*5`.
- `termination_phase` must be present in loop steps.

## Prompt Placeholders

- `{{PROMPT}}`
- `{{SESSION}}`
- `{{PROJECT}}`
- `{{DYNAMIC_CONTEXT}}`
- `{{PHASE_BRIEFING}}`
- `{{FORWARD_REPORT}}`
- `{{SESSION_CONTEXT}}`
- `{{USER_CONTEXT}}`

## CLI

```bash
loopfarm init
loopfarm programs
loopfarm programs list --json
loopfarm "Implement a streaming parser"
loopfarm --program implementation "Improve tail latency"
loopfarm --project edge-agent "Refactor monitor API"
```
