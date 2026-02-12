# Writing Mode Guide

Reference for `loopfarm --mode writing`. Read this before planning, drafting, or
reviewing documentation/prose work.

## Operational Checklist

Before finishing a writing-mode issue, verify:

- You selected the correct document type template (README, paper, or API docs).
- Technical claims are verified against the source code.
- External claims include citations or links.
- Examples are complete and runnable (or clearly marked as pseudocode).
- The revision checklist near the end of this guide is satisfied.

## Core Principle

Writing is thinking. If you cannot state the document's purpose in one sentence,
you do not understand it yet. Every section, paragraph, and sentence should serve
that purpose. Remove everything else.

## General Rules

1. **Active voice, first person.** "We implement" not "the algorithm was
   implemented." Passive voice obscures agency.
2. **One idea per paragraph.** Each paragraph opens with a sentence that
   summarizes its content. If you cannot write that sentence, split or merge.
3. **Short sentences.** Compound sentences with multiple clauses force the reader
   to hold too much in working memory. Break them.
4. **No hedging.** Remove "we believe," "it seems," "arguably," "it is worth
   noting that." Make claims and back them with evidence.
5. **No filler.** Remove "in order to" (use "to"), "it is important to note
   that" (just state it), "as a matter of fact" (delete).
6. **Define terms on first use.** No exceptions. Acronyms are spelled out once,
   then abbreviated.
7. **Concrete over abstract.** Prefer examples, code snippets, and diagrams over
   prose descriptions of behavior.
8. **Serial comma.** Always: "A, B, and C" not "A, B and C."

## Document Types

### README

Structure for a project README:

```
# Project Name

One-sentence description of what it does and why.

## Quick Start

Minimal steps to install and run. Code block, not prose.

## Usage

Common operations with concrete examples. One subsection per
major feature or command.

## Architecture (optional)

How it works internally. Diagram if the system has more than
two components. Prefer ASCII art or drawl output.

## API Reference (optional, or link)

If the API is small, inline it. Otherwise link to generated
docs or a separate file.

## Configuration

Environment variables, config files, flags. Table format:

| Variable | Default | Description |
|----------|---------|-------------|

## Development

How to build, test, and contribute. Include exact commands.

## License (if public)
```

**README anti-patterns:**

- Opening with "Welcome to..." or "This project is a..."
  Open with what it does: "Semantic search API backed by Turbopuffer."
- Feature lists without examples. Every claim needs a code block or command.
- Badges. They add noise and go stale. Omit unless the project is public and CI
  status matters to users.
- "Table of Contents" for READMEs under 200 lines. The headings are the TOC.

### Academic / Technical Paper

Structure (Schulzrinne, Peyton Jones):

```
Title           — Specific. No filler words.
Abstract        — Four sentences: context, problem, approach, result.
Introduction    — Motivate the problem for a general audience.
                  End with a numbered contribution list.
Background      — Only what the reader needs to follow YOUR paper.
                  Not a survey. Cut ruthlessly.
Method/Approach — Your key idea. Enough detail to reproduce.
Evaluation      — Evidence. Enough detail to duplicate results.
Related Work    — Compare and contrast, do not just list.
Conclusion      — What it means, not what you did.
```

**Paper rules:**

- The abstract is self-contained. A reader who sees only the abstract should know
  the problem, approach, and result.
- The introduction is not the abstract expanded. It motivates, contextualizes,
  and states contributions. It does not summarize results.
- Related work is grouped by idea, not by paper. Each paragraph covers an
  approach or family of techniques, with comparison to your work.
- Never disparage prior work. State limitations factually. Give credit.
- Number only equations you reference. Numbering everything is noise (Knuth).
- Design notation at the beginning. Remind the reader of symbol meanings when
  they reappear after a gap (Halmos).

**The four-sentence test.** Before outlining, write one sentence for each:

1. What is the problem?
2. Why is it hard / why do existing approaches fail?
3. What is your key idea?
4. What is the evidence that it works?

If those sentences are clear, you have a paper.

### API / Reference Documentation

Structure per module or endpoint:

```
## Module/Endpoint Name

One-sentence purpose.

### Signature / Request

Exact function signature, HTTP method + path, or CLI usage.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|

### Returns / Response

Type, shape, and meaning. Include a concrete example.

### Errors

What can go wrong and what the caller should do about it.

### Example

Complete, runnable example. Not a fragment.
```

**API doc rules:**

- Every parameter is documented. No exceptions.
- Examples are complete and runnable. The reader should be able to copy-paste.
- Error documentation is as important as success documentation. List error codes,
  their meaning, and recovery actions.
- Do not describe implementation details unless they affect the caller (e.g.,
  "this endpoint is eventually consistent").
- Keep descriptions factual. "Returns the user object" not "This powerful
  endpoint retrieves the user object for you."

## Sentence-Level Craft

### Word precision

- "i.e." means "that is" (restating). "e.g." means "for example" (giving
  instances). Do not confuse them.
- "its" is possessive. "it's" is a contraction of "it is." Test: substitute "it
  is" and check if the sentence still works.
- "only" changes meaning by position: "I only eat apples" (eating is all I do
  with them) vs. "I eat only apples" (apples are the only thing I eat).
- "which" introduces non-restrictive clauses (use a comma). "that" introduces
  restrictive clauses (no comma). "The module, which handles auth, is new" vs.
  "The module that handles auth is new."

### Hyphenation

- Hyphenate compound adjectives: "high-performance system."
- Do not hyphenate noun phrases: "The system has high performance."
- Hyphenate compounds with "well," "ill," "self" before nouns: "well-known
  algorithm," "self-contained proof."

### Numbers and units

- Spell out numbers under ten in prose. Use digits for 10+.
- Non-breaking space between number and unit: "10 ms" not "10ms."
- Units are never italicized.
- Distinguish bits and bytes: "10 kb" (kilobits) vs. "10 kB" (kilobytes).

### Citations (for papers)

- Never use citation numbers as nouns. Not "as shown in [15]" but "Smith et
  al. [15] show that..."
- "et al." — period after "al" only, never italicized. Use for three or more
  authors.
- Alphabetize reference lists by author last name.
- Verify BibTeX entries from publisher exports. Bracket proper nouns and
  acronyms: `{GPU}`, `{Markov}`.

## Anti-Patterns

| Pattern | Problem | Fix |
|---------|---------|-----|
| "Welcome to X" opening | Wastes the reader's first impression | Open with what it does |
| Wall of text with no headings | Unnavigable | Add structure, one idea per section |
| Explaining what you did instead of why it matters | Buries the significance | Lead with impact |
| "For more information, see..." without a link | Dead end | Provide the actual reference |
| Inline code for emphasis | Confuses code and prose | Use **bold** or *italic* |
| Screenshots of terminal output | Unsearchable, inaccessible | Use code blocks |
| Documenting internals in user-facing docs | Confuses audience | Separate concerns |
| Over-hedging ("we believe," "it seems") | Undermines confidence | State claims, cite evidence |
| Listing papers without comparison | Not a related work section | Group by idea, compare to your work |

## Revision Checklist

Before considering a document complete, verify:

- [ ] Every heading describes a coherent unit. No heading contains unrelated material.
- [ ] Every paragraph has a lead sentence.
- [ ] Every term is defined before or at first use.
- [ ] Every code example runs (or is clearly marked as pseudocode).
- [ ] Every external claim has a citation or link.
- [ ] No sentence uses passive voice without good reason.
- [ ] No paragraph exceeds ~6 sentences.
- [ ] Notation/terminology is consistent throughout.
- [ ] The document is self-contained — a reader should not need to read other
  documents to understand the core content.

## References

These are the sources behind this guide. Consult them for deeper treatment:

- Peyton Jones, "How to Write a Great Research Paper" (talk)
- Heiser, "Guide to Technical Writing"
- Owens, "Common Errors in Technical Writing"
- Schulzrinne, "Writing Systems and Networking Articles"
- Jarosz, "Common Mistakes in Technical Writing"
- Knuth, Larrabee, Roberts, "Mathematical Writing"
- Halmos, "How to Write Mathematics"
