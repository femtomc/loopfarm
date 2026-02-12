THIS IS A DOCUMENTATION PHASE.

The user asked us to address:

---

USER PROMPT: **{{PROMPT}}**

---

{{DYNAMIC_CONTEXT}}

Use the injected **Forward Pass Report** to scope documentation work to what
changed in the current implementation cycle.

If the prompt targets a specific project, ignore unrelated changes outside that
scope.

---

## Forward Pass Report

{{FORWARD_REPORT}}

## Workflow

1. Inspect relevant code and open `synth-issue` items tied to the active implementation epic.
2. Update docs/prose so they match the current code and issue state.
3. Coordinate doc follow-ups through `synth-issue` (open/update issues as needed).
4. If code changes are required, file issues instead of implementing them here.
5. Keep this phase focused on documentation accuracy, clarity, and runnable examples.

Do NOT perform implementation refactors in this phase.

Ignore unrelated dirty state in the monorepo; other agents may be working in
parallel.

## Required Phase Summary

At the end of your final response, include a concise 2-4 sentence summary
between these markers exactly:

---LOOPFARM-PHASE-SUMMARY---

<summary>
---END-LOOPFARM-PHASE-SUMMARY---
