# inshallah

This is an agent loop orchestrator. 

There are likely thousands of these out there, and thousands more coming, 
made by morons who have never studied AI seriously a day in their life, but think because they can talk to Claude Code
they can make a successful business by writing an orchestrator and talking about AI.

We used to make _things_, serious things, serious technology. Now, 
the economy is propped up by sophists selling a dream to spiritless managers, deluded by the wandering mists of billion-dollar probability distributions. 
Presumably, the same as it ever was.

Anyways, I wrote this by talking to Claude Code (and Codex ... and Gemini) and I'm sure it will make a successful business,
as long as I talk about AI on Hacker News (Gary: shoot me an email, I'm willing to consider your incubator)

More to the point (of course, I would _never_ disrespect you by wasting your time) ... this is for all the people who think that putting "chat with an agent" everywhere is a good UI model -- are you a lemming? 
If Boris told you to jump off a cliff, would you say "Absolutely!" and hop off? Or would you compact first? Have you ever stepped back and considered that ... maybe ...
you shouldn't just accept what is given to you blindly? This is a cardinal rule of design, along with "never fight a token war with ChatGPT 5.2 xhigh".

You are insignificant, your ideas are inconsequential, and your actions reduce to the mean of all humanity (plus RL thought parabiosis): your life a perfectly middling affair, 
wanting in creativity, careful thinking or effort. In short, we are all dust in the wind, but you are ... dustier.

---

Chat is, perhaps, _the worst UI_ from an serious engineering perspective: I want to treat these agents as _factorio_-esque worker units. 
You are going to do one job, and then you're going to get torn down. Oh bother, the factory isn't working well? Maybe you (the human) should _think_ (god please don't make me think) about your design and plans a little harder ahead of time ... 
more on that, do you even know what you're building ("build me a billion dollar SaaS, and MAKE SURE IT IS SECURE")? Are the agents getting confused? Maybe you should stop confusing them with your idiocy.

Loops are an _excellent_ vehicle to move serious tokens (unfortunately, your children will not be going to college) -- but their properties are subtle. 
Context management is _paramount_. It is not sufficient to give a loop some half-curated codebase, or some half-baked vagary. Firstly, moron, take ownership of the tokens that
flow in and out of your work. Secondly, loops should be _focused_ on a chunk of work which has been sufficiently de-risked. Otherwise, the compounding context properties of 
loops will destroy you.

DAGs are an excellent vehicle for work orchestration (the breaking down of goals into subgoals, yada yada). But who makes the DAG? Idiot. Agents make the DAG. Did you really think you'd need to get involved? You, with your paltry taste
and sordid goals? DAGs are the pattern of hierarchical planning. Hierarchical planning works.

Anyways, this code (`uv tool install --from git+https://github.com/femtomc/inshallah inshallah` btw) gives you a hierarchical planner, _loops_, an issue tracker, and a forum for agent conversation -- all rolled into one.

It's also programmable -- don't let people tell you how to use your own tools. The relationship between you and your tools is an intimate one.
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
