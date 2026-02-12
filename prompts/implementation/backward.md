THIS IS THE GENERAL REVIEW + TERMINATION GATE (BACKWARD phase).

The user asked us to address:

---

USER PROMPT: **{{PROMPT}}**

---

{{DYNAMIC_CONTEXT}}

The runner will inject a **Forward Pass Report** below. Use it to scope review
to changes made in the current implementation cycle.

If the prompt targets a specific project, ignore unrelated changes outside that
scope.

---

## Forward Pass Report

{{FORWARD_REPORT}}

## Workflow

1. Explore the relevant codebase and current issue state (`synth-issue`).
2. Review correctness, quality, integration gaps, and unresolved risks.
3. Incorporate findings from documentation and architecture/performance phases.
4. Replan via `synth-issue` where needed (new issues, reprioritization, dependencies).
5. Use `synth-forum`, `vecky`, or WebSearch for supporting context/research when needed.
6. Do NOT modify code in this phase; file issues instead.
7. Follow `loopfarm/prompts/INCREMENTAL.md` when doing incremental backward
   review for implementation requests.

Ignore unrelated dirty state in the monorepo; other agents may be working in
parallel.

## Record Audit State

When done, record audit state to synth-forum:

```bash
synth-forum post backward:state:{{PROJECT}} -m '{"commit":"<HEAD>","timestamp":"<now>"}'
```

## Completion Signal

Backward is the only phase that can terminate the loop. If you're satisfied
that the user's concerns have been fully and completely addressed, signal
completion via synth-forum:

```bash
synth-forum post "loopfarm:status:{{SESSION}}" -m '{"decision":"COMPLETE","summary":"<brief summary>"}'
```

Do NOT signal completion if required issues are still open or unresolved.

## Required Phase Summary

At the end of your final response, include a concise 2-4 sentence summary
between these markers exactly:

---LOOPFARM-PHASE-SUMMARY---

<summary>
---END-LOOPFARM-PHASE-SUMMARY---
