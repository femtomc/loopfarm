# Issue-DAG Runner State Machine

`loopfarm issue orchestrate-run --root <id>` (and prompt mode) runs a
deterministic select → execute → maintain loop over an issue DAG.

## Shape

```text
validate(root)
repeat up to max_steps:
  if termination.is_final: stop(root_final)
  selection = select_next_execution(root, tags, resume_mode)
  if selection is None: stop(no_executable_leaf)
  execute_selection(selection)   # orchestrator_planning or spec_execution
  maintenance(selection)         # reconcile control-flow ancestors (or full subtree)
  validate(root)
stop(max_steps_exhausted)
```

## Termination Gate (Root Final)

The root is **final** only when:

- root `status in {closed, duplicate}`
- root `outcome in {success, failure}`
- no active descendants remain under the root

`outcome=expanded` is explicitly non-final and is only valid while descendants
are still active.

## Execution Postconditions (Per Step)

After a selection executes, the selected issue must end in a terminal state:

- `status in {closed, duplicate}`
- `outcome in {success, failure, expanded, skipped}`

Route-specific constraints:

- `route=orchestrator_planning` must end with `outcome=expanded`
- `route=spec_execution` must not end with `outcome=expanded`

## Stop Reasons

Orchestration runs stop with one of:

- `root_final`: root satisfied the termination gate.
- `no_executable_leaf`: no ready/resumable leaf exists under the root.
- `max_steps_exhausted`: step budget reached before root final.
- `error`: selection execution failed or postconditions were violated.

## Maintenance Modes

- incremental (default): `reconcile_control_flow_ancestors(issue_id, root_issue_id=...)`
- full (`--full-maintenance`): `reconcile_control_flow_subtree(root_issue_id)`
