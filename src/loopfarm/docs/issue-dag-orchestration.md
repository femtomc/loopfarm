# Issue-DAG Orchestration

Loopfarm represents hierarchical planning and recursive execution directly in the
issue tracker: issues are plan nodes, and dependencies encode a DAG.

This contract keeps orchestration programmable with exactly two file surfaces:

- `.loopfarm/orchestrator.md`
- `.loopfarm/roles/*.md`

No team TOML specs or program TOML routing is required.

## Minimal Programming Model (Core Contract)

This section is the canonical decision record for the minimal loopfarm "core":
what users edit, where state lives, and which CLI entrypoints are stable.

### Programmable Surfaces (User-Editable)

Only two files are treated as user-authored "code" by the orchestrator:

- `.loopfarm/orchestrator.md`: used when a selected leaf is non-atomic and must be
  decomposed into child issues.
- `.loopfarm/roles/*.md`: used when a selected leaf is atomic and routed to
  execution.

Everything else under `.loopfarm/` is runtime state (issue/forum SQLite stores,
session logs, caches) and is explicitly **not** a programmable surface.

### Canonical Unit of Work + State

- Canonical unit of work: **one issue** (a node in the DAG).
- Canonical state: the **issue tracker** (status/outcome/tags + dependency edges).
- Shared memory / provenance: the **forum**, stored as topic/message history.

Topic conventions:

- per-node thread: `issue:<id>`
- run-/feature-level threads: e.g. `loopfarm:feature:issue-dag-orchestration`

### Minimal Orchestration Schema

Required tags (minimal set used by the orchestrator):

- `node:agent`: marks executable/plannable nodes.
- `granularity:atomic`: marks leaves that should execute via a role (not expand).
- `node:control` plus exactly one `cf:*` tag: marks control-flow aggregators.

Required edges (minimal set used for DAG semantics):

- `parent`: hierarchy / decomposition.
- `blocks`: ordering / gating.

Required outcomes (terminal result taxonomy):

- `success`, `failure`, `expanded`, `skipped`

Everything else is optional labeling/routing sugar (for example `team:*`,
`role:*`, and `related` edges).

### CLI Contract (Stable vs Internal)

First-class commands (stable UX contract):

- `loopfarm init`
- `loopfarm "<prompt>"` (prompt mode: create a root issue and run orchestration)
- `loopfarm docs list|show|search`
- `loopfarm forum post|read|search`
- `loopfarm issue new|list|ready|show|comment|status|close|reopen`
- `loopfarm issue dep add` and `loopfarm issue tag add|remove`
- `loopfarm issue orchestrate-run --root <id>` (deterministic select->execute loop)
- `loopfarm sessions list|show` (and `loopfarm history` alias)

Internal/advanced commands (debugging/ops; subject to change):

- `loopfarm roles` (explicitly internal)
- `loopfarm issue orchestrate` (selection-only; emits `node.execute`)
- `loopfarm issue reconcile` (control-flow maintenance)
- `loopfarm issue validate-dag` (structural invariants)
- `loopfarm issue delete` (destructive; requires `--yes`)

## Canonical Tag Taxonomy

### Node and Control-Flow Tags

- `node:agent`: executable/plannable issue node.
- `node:control`: control-flow aggregator node.
- `cf:sequence`: control node succeeds only if all children succeed.
- `cf:fallback`: control node succeeds if any child succeeds.
- `cf:parallel`: control node succeeds by majority vote of child outcomes.

### Routing Tags

- `role:<name>`: optional role override for atomic execution.
- `granularity:atomic`: explicit marker that a leaf is executable without further decomposition.
- `team:<name>`: optional label only (kept in emitted event metadata for traceability).

Recommended conventions:

- Use at most one `role:*` tag per node.
- Omit `role:*` on most nodes; atomic routing will default to `worker` when present.
- Use `team:*` only as an optional reporting label.

## Edge Semantics

- `parent` (`P parent C`): hierarchy/decomposition edge (parent owns child).
- `blocks` (`A blocks B`): ordering/gating edge (`B` is not ready while `A` is active).
- `related`: non-execution association.

## Outcomes (Terminal Result Taxonomy)

Loopfarm issues have `status` plus optional terminal `outcome`:

- Terminal statuses: `closed`, `duplicate`
- Outcomes: `success`, `failure`, `expanded`, `skipped`

Rules:

- Outcome can only be set on terminal statuses.
- Reopening a node clears any existing outcome.
- `expanded` is terminal-but-non-final: decomposition happened, and descendants continue work.
- Any node with `outcome=expanded` must have at least one active descendant.

## Minimal Programmability Model

The orchestrator reads two prompt surfaces only:

1. `.loopfarm/orchestrator.md`: used when a selected leaf is non-atomic and must be decomposed.
2. `.loopfarm/roles/<role>.md`: used when a selected leaf is atomic and routed to execution.

Role resolution for atomic leaves:

- explicit `role:<name>` tag if present
- otherwise `worker` if `.loopfarm/roles/worker.md` exists
- otherwise the single available role doc if exactly one exists
- otherwise fail fast and require explicit `role:<name>`

## Orchestrator Decision Procedure (MVP)

```text
def orchestrate(root_id):
    while not root_is_final(root_id):
        leaf = next_ready_leaf(root=root_id, tags=["node:agent"])
        if leaf is None:
            validate_subtree(root_id)
            break

        if not leaf.has_tag("granularity:atomic"):
            run_prompt(".loopfarm/orchestrator.md", issue=leaf)
            close_issue(leaf, outcome="expanded")
            continue

        role = resolve_role_from_tags_and_role_docs(leaf)
        run_prompt(f".loopfarm/roles/{role}.md", issue=leaf)
        reconcile_ancestors(leaf)
```

## Claim and Resume Semantics (MVP)

- Before running any open leaf, orchestrator atomically claims it via `open -> in_progress`.
- If claim fails, orchestrator skips that candidate and retries ready frontier candidates.
- `node.execute` is emitted only after successful claim (or explicit resume), with:
  `id`, `role`, `program`, `mode`, `claim_timestamp`, `claim_timestamp_iso`.

Resume policy:

- `manual` (default): do not auto-adopt `in_progress` nodes.
- `resume`: process resumable `in_progress` leaves before claiming new `open` leaves.

## Root Termination Contract

For `--root <id>` orchestration runs:

- Final stop outcomes are exactly `success` or `failure` on the root.
- `outcome=expanded` on the root is explicitly non-final.
- A root marked `expanded` is valid only while it still has active descendants.

The subtree validator (`loopfarm issue reconcile <root> --root --json`) reports:

- `termination`
- `orphaned_expanded_nodes`
- `errors` and `warnings`

The structural DAG validator (`loopfarm issue validate-dag --root <id>`) reports:

- parent-edge cycles under `--root`
- node typing violations (`node:control`/`cf:*` and `node:agent`/`cf:*`)
- terminal `node:*` issues missing an outcome
- invalid `blocks` wiring
- orphaned expanded nodes

## CLI Entrypoints

```bash
loopfarm issue orchestrate --root <id> --json
loopfarm issue orchestrate-run --root <id> --json
loopfarm issue orchestrate-run --root <id> --max-steps 8 --scan-limit 50 --json
loopfarm issue validate-dag --root <id> --json
```

- `orchestrate`: selection-only routing + `node.execute` payload emission.
- `orchestrate-run`: deterministic execution loop with post-step maintenance.

Stable stop reasons:

- `root_final`
- `no_executable_leaf`
- `max_steps_exhausted`
- `error`

## Forum Provenance (Canonical Event Kinds)

Use forum as shared memory:

- per-node topic: `issue:<id>`
- run-level topic: `loopfarm:feature:issue-dag-orchestration`

Canonical kinds:

- `node.plan`
- `node.memory`
- `node.expand`
- `node.execute`
- `node.result`
- `node.reconcile`

Required fields:

- `node.plan`: `id`, `root`, `team`, `role`, `program`, `summary`
- `node.memory`: `id`, `root`, `summary`
- `node.expand`: `id`, `root`, `team`, `role`, `program`, `control`, `children`
- `node.execute`: `id`, `team`, `role`, `program`, `mode`, `claim_timestamp`, `claim_timestamp_iso`
- `node.result`: `id`, `root`, `outcome`
- `node.reconcile`: `id`, `root`, `control_flow`, `outcome`

Optional provenance fields:

- `issue_refs`: non-empty list of related issue IDs
- `evidence`: non-empty list of evidence entries

`node.replan` is deprecated and should be migrated to `node.reconcile`.

## MVP Non-Goals

- No concurrent execution scheduler.
- No automatic role synthesis beyond explicit role docs.
- No program/team config routing layer.

## See Also

- `steps-grammar`
- `implementation-state-machine`
- `source-layout`
