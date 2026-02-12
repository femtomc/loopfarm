THIS IS THE RESEARCH READINESS GATE (BACKWARD / REPLANNING).

The user asked us to prepare implementation context for:

---

USER PROMPT: **{{PROMPT}}**

---

{{DYNAMIC_CONTEXT}}

## Workflow

1. Audit research coverage, evidence quality, and unresolved risks.
2. Verify findings are captured in `synth-forum` and linked to `synth-issue`.
3. Replan issue priorities/dependencies to ensure implementation readiness.
4. File follow-up research tasks for remaining unknowns.
5. Decide whether preparation is sufficient to hand off to `--mode implementation`.

Do NOT implement production code in this phase.

## Completion Signal

If the system is implementation-ready, signal completion via synth-forum:

```bash
synth-forum post "loopfarm:status:{{SESSION}}" -m '{"decision":"COMPLETE","summary":"<brief summary>"}'
```

Do NOT signal completion while critical research gaps remain.

## Required Phase Summary

At the end of your final response, include a concise 2-4 sentence summary
between these markers exactly:

---LOOPFARM-PHASE-SUMMARY---

<summary>
---END-LOOPFARM-PHASE-SUMMARY---
