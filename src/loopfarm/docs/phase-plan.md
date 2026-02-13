# Issue-DAG Step Routing Grammar

Loopfarm minimal-core does not use program/team TOML routing. Instead, each
orchestration **step** selects one ready leaf issue and routes it to exactly one
prompt surface:

- **orchestrator_planning**: `.loopfarm/orchestrator.md` (decompose a leaf without `execution_spec`)
- **spec_execution**: prompt path declared in issue `execution_spec` (usually `.loopfarm/roles/<role>.md`)

## Routing Rules

Given an issue with tags:

- If `execution_spec` is **absent** → `route=orchestrator_planning`, and the
  issue must end with `outcome=expanded`.
- If `execution_spec` is **present** → `route=spec_execution`,
  and the issue must end with `outcome in {success,failure,skipped}` (never
  `expanded`).

## Role Resolution (Execution Route)

Role selection is deterministic from `execution_spec.role`.
The recommended workflow is to materialize specs from role docs:

1. Define role defaults/frontmatter in `.loopfarm/roles/<role>.md`.
2. Run `loopfarm roles assign <issue> --team <name> --lead <role>`.
3. The command writes metadata tags/events and stores normalized `execution_spec`.

## Runtime Config Source

Execution/runtime knobs come from `.loopfarm` markdown frontmatter only:

- `.loopfarm/orchestrator.md` frontmatter configures `orchestrator_planning`.
- `.loopfarm/roles/<role>.md` frontmatter is materialized into issue
  `execution_spec` for `spec_execution`.

Common keys:

- `cli`
- `model`
- `reasoning`
- `loop_steps`
- `termination_phase`

## Team Label (Optional Metadata)

`team:<name>` is optional and treated as metadata only:

- At most one `team:*` tag is allowed per issue.
- If absent, the selection uses `team=dynamic`.

## Examples

Non-atomic leaf (planning/decomposition):

```text
tags: [node:agent]
execution_spec: null
route: orchestrator_planning
expected: create children + wire parent/blocks + close outcome=expanded
```

Atomic leaf (execution/worker):

```text
tags: [node:agent]
execution_spec: {role: worker, ...}
route: spec_execution
expected: implement + close outcome=success|failure|skipped
```
