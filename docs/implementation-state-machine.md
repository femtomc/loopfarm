# Implementation Mode State Machine

This document defines the implementation-mode phase contract and transition
model used by loopfarm.

## State Machine

```text
planning_once -> (forward^N -> documentation -> architecture -> backward_decision)^K
```

- `planning_once` is optional (`--skip-plan` disables it).
- `forward^N` means forward can repeat within a loop cycle.
- `backward_decision` is the sole termination gate.

## Termination Authority

- Only `backward` is allowed to terminate a session.
- A session completes only when backward writes `decision=COMPLETE` to the
  status topic.

This is encoded in `phase_contract.py` via `termination_gate=True` for
`backward` and checked in the runner through `is_termination_gate(phase)`.

## Phase I/O Contract

| Phase | Consumes | Produces | `synth-issue` writes | `synth-forum` writes |
| --- | --- | --- | --- | --- |
| `planning` | prompt, repo_state | issue_plan | epic, leaf_issues | briefing |
| `forward` | issue_plan, repo_state | code_changes, phase_summary | leaf_issues | briefing, forward_report |
| `documentation` | forward_report, repo_state | doc_updates, phase_summary | documentation_issues | briefing |
| `architecture` | forward_report, repo_state | architecture_findings | implementation_epic | architecture_summary |
| `backward` | phase_summaries, forward_report, repo_state | decision, phase_summary | followup_issues | status, briefing |

## Implementation Mapping

- Contract definitions live in `loopfarm/src/loopfarm/phase_contract.py`.
- Configured plan validation uses `build_state_machine(...)`.
- Runtime termination checks use `is_termination_gate(...)`.

