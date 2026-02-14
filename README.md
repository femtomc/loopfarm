# inshallah

This is an agent loop orchestrator. 

There are likely thousands of these out there, and thousands more coming, 
made by morons who have never studied AI seriously a day in their life, but think because they can talk to Claude Code
they can make a successful business by writing an orchestrator and talking about AI.

We used to make _things_, serious things, serious technology. Now, 
the economy is propped up by sophists selling a dream to spiritless managers, deluded by the wandering mists of billion-dollar probability distributions. 
Can a monkey be the Buddha? More importantly, can a monkey get VC funding for an AI startup?

Anyways, I wrote this piece of scripture by talking to Claude Code (and Codex ... and Gemini) and I'm sure it will make a successful religion,
as long as I talk about AI on Hacker News (Gary: shoot me an email, I'm willing to consider your incubator)

More to the point (I would _never_ disrespect you by wasting your time) ... this is for all the people who think that putting "chat with an agent" everywhere is a good UI model -- are you a lemming?
If Boris told you to jump off a cliff, would you say "Absolutely!" and hop off? Or would you compact first? Lowly dog, have you ever stepped back and considered that
you shouldn't just accept what is given to you blindly? This is a cardinal rule of design, along with "never fight a token war with ChatGPT 5.2 xhigh".

More on the nose: you are insignificant, your ideas are inconsequential, and your actions reduce to the mean of all humanity (plus RL thought parabiosis). Your life is a perfectly middling affair, 
wanting in creativity, careful thinking or effort. In short, we are all dust in the wind, but you are ... dustier.

But you could become _more than you are_, if you join my in-group, learn the shibboleths, and take this pilgrimage with me.

---

Chat is, perhaps, _the worst UI_ from an serious engineering perspective: I want to treat these agents as _factorio_-esque worker units. 
You are going to do one job, and then you're going to get torn down. Oh bother, the factory isn't working well? Maybe you (the human) should _think_ (god please don't make me think) about your design and plans a little harder ahead of time ... 
more on that, do you even know what you're building ("build me a billion dollar SaaS, and MAKE SURE IT IS SECURE")? Are the agents getting confused? Maybe you should stop confusing them with your idiocy.

Loops are an _excellent_ vehicle to move serious tokens (unfortunately, your children will not be going to college) -- but their properties are subtle. 
Context management is _paramount_. It is not sufficient to give a loop some half-curated codebase, or some half-baked vagary. Firstly, moron, take ownership of the tokens that
flow in and out of your work. Secondly, loops should be focused on chunks of work which have been sufficiently de-risked ... nearly decomposed to determinism. Otherwise, the compounding context properties of loops will destroy you and your holy work.

DAGs are a wondrous vessel for work orchestration (the breaking down of goals into subgoals, yada yada). But who makes the DAG? Will you, surly idiot, first of your name, make the DAG? No, agents make the DAG. Did you really think you'd need to get involved? You, with your paltry taste
and sordid goals? DAGs are the pattern of hierarchical task decomposition and planning. Hierarchical planning works.

---

```
uv tool install --from git+https://github.com/femtomc/inshallah inshallah
```

Anyways, this code gives you a hierarchical planner, _loops_, an issue tracker, and a forum for agent conversation -- all rolled into one.

It's also programmable in the most obvious of ways -- don't let people tell you how to use your own tools. The relationship between you and your tools is an intimate one.
Most companies start from a place of disrespect: "you don't know how to use your tools ... we do." The gift of a programmable tool is the ultimate form of respect ... 
just ask your agent about it.

## How to use

Install via `uv tool install --from git+https://github.com/femtomc/inshallah inshallah` and then poke around the CLI or have your agent do it. It's self-explanatory. If it's not self-explanatory, it's not ready for usage, and you shouldn't use it.

## Still around?

This package is based on a few simple premises:
* Frontier agents use CLI-based issue trackers (really, any CLI-based tool with careful design) extremely well
* Agents _may be_ remarkably good at decomposing goals into sequences of tasks
* Agents _may be_ remarkably good at constructing teams of other agents to execute said tasks
* Someone should wrap a bow on this, make it programmable in a straightforward way, with a good UI ("finding 3 patterns in 2 files" you won't find dipshit decisions like this in our UI)

Here's a package which is intended to be _as minimal as possible_ towards this goal. A "pi-like" Gas Town, if you will.

### The orchestrator loop

The orchestrator is a `select → execute → validate` loop. On each step:

1. **Select** a ready leaf from the issue DAG (open, unblocked, no open children, sorted by priority).
2. Route it through execution configuration resolution (more on this below) to determine which CLI backend to use, which model, and which prompt template.
3. **Execute** by spawning a subprocess (Claude, Codex, Gemini, etc.) with the rendered prompt. The agent runs, does its work, and closes the issue via the `inshallah` CLI.
4. **Validate** whether the DAG is done. Failures and review rejections do **not** halt the run: they are logged to the forum and the orchestrator is re-invoked to expand the issue into remediation children. If everything collapses back to the root with `success`: done. Otherwise: loop.

There's an optional **review phase** after each successful execution: a reviewer agent independently evaluates the work and either passes it or marks it `needs_work`. The reviewer does not create new issues. There's also a **collapse review** phase that fires when all children of an expanded node finish — an aggregate check that the parts actually satisfy the whole; if it fails, the reviewer marks `needs_work` and the orchestrator expands follow-up remediation work.

The loop terminates when the DAG reaches a final state (collapse all the way back to the root), or when it hits the step limit. The runner should not reach "no executable leaves"; if it does, it re-invokes the orchestrator to repair/expand the DAG. On resume (`inshallah resume <root-id>`), any in-progress issues are reset to open and the loop picks up where it left off.

### Programmability: roles and execution configuration

Roles are markdown files in `.inshallah/roles/` with YAML frontmatter. `inshallah init` scaffolds three:

- **orchestrator** — decomposes root goals into child issues, assigns roles, manages dependency order. This is the planner.
- **worker** — executes exactly one atomic issue end-to-end (code, tests, docs, whatever), then closes it with a terminal outcome.
- **reviewer** — independently verifies completed work. If the work is good, it does nothing. If there are real functional issues, it marks the issue `needs_work` and explains why; the orchestrator expands remediation children.

Each role specifies its own `cli`, `model`, and `reasoning` level in its frontmatter. You can create as many roles as you want — a `researcher` that uses Claude Opus for deep analysis, a `scripter` that uses a fast model for boilerplate, whatever.

Execution configuration resolution is 3-tiered, each layer overriding the last:

1. **`orchestrator.md` frontmatter** — global defaults for every issue.
2. **Role frontmatter** — role-specific overrides (e.g., the reviewer uses a different model than the worker).
3. **`execution_spec` on the issue itself** — per-issue explicit overrides. The orchestrator agent sets these when it decomposes work.

Roles are also self-documenting: the orchestrator agent sees `{{ROLES}}` in its prompt, which auto-expands to a catalog of all available roles with their descriptions. So when the orchestrator decides which role to assign to a child issue, it has the full menu in front of it.

### The DAG: expansion and contraction

The issue DAG has two edge types:

- **`parent`** — hierarchical decomposition. "This issue is a child of that issue."
- **`blocks`** — execution ordering. "This issue must close before that issue can start."

**Expansion** is how the DAG grows. When the orchestrator selects an issue and decides it isn't atomic, it:

1. Creates child issues under the parent, each with a role and priority.
2. Adds `blocks` edges between children that need to run sequentially.
3. Closes the parent with `outcome=expanded`.

The `expanded` outcome is special: it means "I'm done as a planning node, my real work lives in my children." Expanded nodes are **transparent** for completion checks — the DAG doesn't consider them pending work. They're delegation markers.

**Contraction** is how the DAG resolves. As workers close leaf issues with outcomes (`success`, `skipped`) or signal `failure`, the set of ready leaves shifts. Blocking edges dissolve as their prerequisites close. When an issue fails (or is marked `needs_work`), the orchestrator expands it into smaller remediation leaves and the loop continues.

When all children of an expanded node reach successful terminal outcomes, the node becomes **collapsible**. If a reviewer is configured, a collapse review fires: the reviewer checks whether the aggregate children actually satisfy the parent's original specification. If so, the parent is promoted to `success`. If not, the reviewer marks `needs_work` and the orchestrator creates new remediation children — the DAG re-expands locally.

This is the breathing pattern: the DAG expands when planning decomposes goals, and contracts when execution closes leaves. Failures and `needs_work` are not halts; they are triggers for re-expansion. The whole thing converges when everything collapses back to the root with `success`.

```
          root (expanded)
         /    \
     auth      crud (blocked by auth)
    /    \
 schema  jwt
   ✓      ✗ → re-orchestrate
```

The DAG is stored as flat JSONL. No external database, no migration headaches. Issues are human-readable, greppable, and durable across sessions. The forum (also JSONL) stores coordination messages between agents — execution logs, review outcomes, status updates — providing a persistent audit trail.
