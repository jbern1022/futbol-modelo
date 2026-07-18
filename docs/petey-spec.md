# Petey — v1 Design Spec

Named for Peter Brand (Jonah Hill's character in *Moneyball*, based on Paul
DePodesta) — the analyst who trusted the numbers over the scouts' gut. Petey
is a conversational layer on top of Futbol Modelo's real data: not a chatbot
that makes things up, a narrow interface that answers real questions using
real, pre-validated queries.

**Not "Betting Buddy."** Deliberately renamed to avoid gambling-adjacent
framing — this is a stats/analytics assistant, not a wagering tool, and the
portfolio framing matters.

## Core design principle

**Ollama never writes SQL, and never sees the schema.** It does exactly two
narrow jobs:
1. Translate a free-text question into a small, strictly-typed JSON filter
   (fields + operators, both from a fixed allowlist)
2. Turn a query *result* into a conversational sentence

Everything in between — validating the JSON, compiling it into SQL, running
it — is deterministic backend code with zero LLM involvement. If Ollama
proposes a field or operator not on the allowlist, the request is rejected
outright before it gets anywhere near the database. Safety comes from the
validator, not from trusting the model to behave.

## Two entry points, one underlying mechanism

### 1. Common Questions (preset buttons, no typing)
- "How's [team] been playing lately?"
- "What's the model's take on [upcoming match]?"
- "How accurate are your [market] predictions?"
- "Head-to-head: [team A] vs [team B]"

Each maps directly to one fixed, hand-written parameterized query. No LLM
involved at all for these — pure UI convenience.

### 2. Ask Your Own Question (free text)
User types anything. Ollama's only job: translate it into a JSON filter tree
using **only** allowlisted fields/operators, e.g.:

```json
{
  "and": [
    {"field": "market", "op": "=", "value": "CORNERS"},
    {"field": "avg_stated_prob", "op": ">", "value": 0.6},
    {"field": "outcome", "op": "=", "value": "hit"}
  ]
}
```

Backend validates every field/operator against the allowlist, rejects
anything unrecognized, then deterministically compiles the validated JSON
into a `WHERE` clause appended to one fixed, safe base query. Ollama never
generates SQL directly at any point.

**Allowlisted fields (v1):** `market`, `league`, `team`, `outcome`,
`n_predictions`, `avg_stated_prob`, `hit_rate`, `kickoff_date`
**Allowlisted operators (v1):** `=`, `>`, `<`, `>=`, `<=`, `and`, `or`

## Self-improving FAQ loop

Every custom question (raw text + resulting JSON + timestamp) logs to a new
table, `petey_queries`. Periodically review the most common real patterns and
promote them into new preset buttons — the common-questions list gets
smarter from actual usage, not guesswork.

## Components to build

| Component | Est. hours |
|---|---|
| Ollama connectivity + boolean-JSON prompt design | 2 |
| Backend allowlist + strict validator | 1.5 |
| JSON-to-SQL compiler (safe, deterministic) | 1.5 |
| `petey_queries` logging table | 0.5 |
| Common-questions preset buttons (backend queries) | 1 |
| Frontend chat UI (presets + custom input) | 1.5 |
| Testing (valid / invalid / ambiguous / empty-result cases) | 1.5 |
| **Total** | **~9.5 hours (3-4 sessions)** |

## Open questions for next session
- Confirm Ollama is actually running and reachable in the homelab
  (`docker ps | grep ollama`, `docker exec ollama ollama list`) — never
  actually verified this
- Which model to use for intent classification — needs to be fast and
  reliable at structured output, not necessarily large/general-purpose
- Where does the chat UI live — its own page (`/petey`), or a
  widget/drawer on existing pages?
- Rate limiting / abuse handling for the public-facing custom question input,
  since this is genuinely a public site now

## Resolved design decisions

See docs/adr/petey-decisions.md for the full set of architectural
decision records (ADR-001 through ADR-011), covering the query-builder
approach, timeouts, honesty thresholds, and every other locked-in design
choice with full context and rationale.
