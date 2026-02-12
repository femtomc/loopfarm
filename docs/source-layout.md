# Source Layout

`loopfarm` source is organized by concern:

```text
src/loopfarm/
├── cli.py                 # top-level entrypoint / command dispatch
├── runner.py              # loop runtime facade
├── issue.py               # issue command + service facade
├── forum.py               # forum command + service facade
├── monitor.py             # monitoring server/frontend
├── init_cmd.py            # scaffold command
├── backends/              # model backend adapters (codex/claude/gemini/kimi)
├── runtime/               # orchestration internals
│   ├── config.py          # .loopfarm/loopfarm.toml parsing
│   ├── control.py         # pause/resume/stop control-plane logic
│   ├── events.py          # event datatypes
│   ├── forward_report.py  # forward-pass diff/report capture
│   ├── orchestrator.py    # phase loop execution state machine
│   ├── phase_executor.py  # per-phase execution/retry behavior
│   └── prompt_resolver.py # prompt rendering + injections
└── stores/                # persistence and state storage
    ├── state.py           # state dir resolution + timestamps
    ├── issue.py           # issue SQLite store
    ├── forum.py           # forum SQLite store
    └── session.py         # session/control/briefing topic store
```

This keeps top-level modules focused on user-facing commands while grouping
runtime internals and persistence logic in dedicated packages.
