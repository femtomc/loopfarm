# Phase Plan Grammar

Loopfarm uses a mode-agnostic phase-plan string to define loop structure.

Use it via `--phase-plan` (legacy alias: `--loop`).

## Grammar

```ebnf
phase_plan   := token ("," token)*
token        := phase [repeat]
phase        := alias
repeat       := "*" integer | ":" integer | integer
integer      := [1-9][0-9]*
```

Canonical repeat syntax is `*N` (`forward*5`). Legacy repeat forms
(`forward5`, `forward:5`) are accepted for compatibility.

## Aliases

- `planning`: `plan`, `planning`
- `forward`: `forward`, `fwd`
- `research`: `research`, `investigate`, `discovery`
- `curation`: `curation`, `curate`, `triage`
- `documentation`: `documentation`, `docs`, `doc`
- `architecture`: `architecture`, `arch`, `performance`, `perf`
- `backward`: `backward`, `review`, `replan`, `replanning`

## Validation Rules

- `planning` may only appear at the beginning.
- `planning` and `backward` cannot be repeated.
- At least one loop phase must remain after optional leading `planning`.
- `backward` is required for completion/termination checks.

## Examples

Implementation mode:

```text
planning,forward*5,documentation,architecture,backward
```

Research mode:

```text
planning,research*3,curation,backward
```

Legacy-compatible examples:

```text
planning,forward5,documentation,architecture,backward
plan,discovery:3,curate,replan
```

