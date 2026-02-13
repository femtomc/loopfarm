# Issue-DAG Step Routing Grammar

Loopfarm minimal-core does not use program/team TOML routing. Instead, each
orchestration **step** selects one ready leaf issue and routes it to exactly one
prompt surface:

- **planning**: `.loopfarm/orchestrator.md` (decompose a non-atomic leaf)
- **execution**: `.loopfarm/roles/<role>.md` (execute an atomic leaf)

## Routing Rules

Given an issue with tags:

- If `granularity:atomic` is **absent** → `route=planning` (decompose), and the
  issue must end with `outcome=expanded`.
- If `granularity:atomic` is **present** → `route=execution` (run a role prompt),
  and the issue must end with `outcome in {success,failure,skipped}` (never
  `expanded`).

## Role Resolution (Execution Route)

Role selection is deterministic:

1. Use a single `role:<name>` tag if present.
2. Else default to `worker` when `.loopfarm/roles/worker.md` exists.
3. Else use the only available role doc if exactly one exists.
4. Else fail fast and require `role:<name>`.

## Team Label (Optional Metadata)

`team:<name>` is optional and treated as metadata only:

- At most one `team:*` tag is allowed per issue.
- If absent, the selection uses `team=dynamic`.

## Examples

Non-atomic leaf (planning/decomposition):

```text
tags: [node:agent]
route: planning
expected: create children + wire parent/blocks + close outcome=expanded
```

Atomic leaf (execution/worker):

```text
tags: [node:agent, granularity:atomic]
route: execution
expected: implement + close outcome=success|failure|skipped
```
