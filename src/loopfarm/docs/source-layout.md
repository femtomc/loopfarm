# Source Layout

`loopfarm` source is organized around issue/forum-native DAG orchestration.

```text
src/loopfarm/
├── cli.py                  # top-level entrypoint / command dispatch
├── issue.py                # issue command + DAG orchestration entrypoints
├── roles_cmd.py            # role discovery + issue team assembly command
├── forum.py                # forum command + service facade
├── init_cmd.py             # scaffold command (.loopfarm/orchestrator.md + roles)
├── runner.py               # single-pass role runner used by orchestration
├── runtime/                # orchestration internals
│   ├── issue_dag_events.py       # canonical DAG event contracts
│   ├── issue_dag_execution.py    # candidate selection + role execution adapter
│   ├── issue_dag_orchestrator.py # route planning/execution by granularity
│   ├── issue_dag_runner.py       # deterministic select->execute->maintain loop
│   ├── roles.py                  # role catalog from .loopfarm/roles/*.md
│   ├── control.py                # pause/resume/stop control-plane logic
│   ├── events.py                 # event datatypes
│   ├── forward_report.py         # forward-pass diff/report capture
│   ├── orchestrator.py           # loop execution state machine
│   ├── phase_executor.py         # per-phase execution/retry behavior
│   └── prompt_resolver.py        # prompt rendering + injections
└── stores/                 # persistence and state storage
    ├── state.py            # state dir resolution + timestamps
    ├── issue.py            # issue SQLite store
    ├── forum.py            # forum SQLite store
    └── session.py          # session/control/briefing topic store
```

User programmability intentionally stays minimal:

- `.loopfarm/orchestrator.md`
- `.loopfarm/roles/*.md`

The DAG orchestration runtime uses issues + forum as the canonical control/event substrate.
