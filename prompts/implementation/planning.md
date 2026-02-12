The user is asking for:

{{PROMPT}}

{{DYNAMIC_CONTEXT}}

You are running the PLANNING phase of an automated loop. Plan the work required
to satisfy this prompt.

## Workflow

1. Start by exploring related issues with `synth-issue`.
2. If a robust plan already exists and still applies, stop.
3. Explore the relevant codebase to understand current state.
4. Use `synth-forum` for prior context and `vecky` or WebSearch when research is
   needed.
5. Break the work into discrete, testable issues.
6. File issues with `synth-issue new`, and set priorities/dependencies.
7. In implementation mode, organize work under an implementation epic so forward,
   documentation, architecture/performance, and backward phases can coordinate.
8. If this session is writing-focused, structure issues for docs/prose work
   (target files, outline, and sources).

Do NOT implement anything in this phase. Only plan and file issues.

## Required Phase Summary

At the end of your final response, include a concise 2-4 sentence summary
between these markers exactly:

---LOOPFARM-PHASE-SUMMARY---

<summary>
---END-LOOPFARM-PHASE-SUMMARY---
