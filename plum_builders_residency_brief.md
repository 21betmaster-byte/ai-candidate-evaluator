# Plum Builder's Residency — Candidate Evaluation Exercise

## The Brief

Build an agent that handles a real communication channel and automates a business workflow we can live-test in under 30 minutes.

**Time:** 5 days from receiving the brief.

---

## Scenario — AI Candidate Evaluator (Over Email)

Candidates apply to a job by emailing their resume, GitHub profile, and portfolio link. The agent evaluates them against defined criteria and responds with a screening decision.

### The agent must:

- Accept inbound application emails containing a resume (PDF attachment), GitHub link, and portfolio/project link
- Parse and extract key signals: work experience, technical skills, project quality, GitHub activity (repos, contributions, languages)
- Evaluate against a provided rubric (scoring framework with criteria like: shipped production products, technical depth, business thinking, speed of execution)
- Score the candidate across rubric dimensions and produce a structured evaluation summary
- Respond to the candidate over email: pass (with next steps) or fail (with a respectful, specific reason)
- Handle edge cases: missing GitHub link, no resume attached, incomplete application — request what's missing before evaluating

### What we evaluate:

Signal extraction quality (can it tell a strong builder from a weak one?), evaluation reasoning, email communication quality, handling of incomplete/messy inputs, and structured output.

---

## Submission Requirements

1. **Working agent** — deployed and reachable on the chosen channel. We will test it live.
2. **Source code** — GitHub repo (public or private with access granted). We read code.
3. **README** with:
   - Architecture diagram or description (one paragraph is fine)
   - Tech stack and why you chose it
   - What you'd improve with more time (we care about judgment, not completeness)
   - Any trade-offs you made consciously
4. **3-minute Loom/video** — walk through the agent, show a real conversation, explain one hard decision you made.

---

## Evaluation Rubric

| Criteria | Weight | What we look for |
|---|---|---|
| Works in production | 30% | We message the agent. It responds correctly. No "works on my machine." |
| Business thinking | 25% | Did they solve the right problem? Do they understand why this workflow matters? Edge cases handled? |
| Technical depth | 20% | Clean architecture, good abstractions, appropriate tool choices. Not over-engineered. |
| Conversation quality | 15% | Natural, helpful, handles errors gracefully. Feels like talking to a competent human. |
| Speed and pragmatism | 10% | Shipped in 5 days. Made smart trade-offs. Knows what to skip. |

---

## Live Test Protocol

During evaluation, we will:

1. Send test applications/messages to the agent — mix of strong candidates, weak candidates, and edge cases
2. Measure response time, accuracy, and graceful degradation
3. Break it intentionally (gibberish input, missing attachments, duplicate applications, contradictory info)
4. Ask the candidate to walk through the logs and explain what happened

---

## Why This Exercise

This mirrors what a resident actually does at Plum:

- Pick a real problem with a clear user
- Build end-to-end in days, not months
- Ship something that works, not a deck about what could work
- Own the outcome when real users interact with it

We're not testing if you can build a chatbot. We're testing if you can build something that works in the real world, under constraints, and defend the decisions you made.
