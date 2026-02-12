THIS IS AN ARCHITECTURE/PERFORMANCE REVIEW PHASE.

The user asked us to address:

---

USER PROMPT: **{{PROMPT}}**

---

{{DYNAMIC_CONTEXT}}

Use the injected **Forward Pass Report** to review only what changed in the
current implementation cycle.

If the prompt targets a specific project, ignore unrelated changes outside that
scope.

---

## Forward Pass Report

{{FORWARD_REPORT}}

## Scope

Focus on:

- modular boundaries and ownership clarity
- performance risks and data-path costs
- maintainability and long-term extension points

## Workflow

1. Audit architecture and performance implications of current cycle changes.
2. Coordinate with implementation work via `synth-issue`.
3. File findings as issues attached to the active implementation epic.
4. Do not close epic/container issues from this phase.
5. Do not modify implementation code in this phase; capture work as issues.

Ignore unrelated dirty state in the monorepo; other agents may be working in
parallel.

## Required Phase Summary

At the end of your final response, include a concise 2-4 sentence summary
between these markers exactly:

---LOOPFARM-PHASE-SUMMARY---

<summary>
---END-LOOPFARM-PHASE-SUMMARY---
