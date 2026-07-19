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

## Confirmed infrastructure

- **Ollama is live and reachable** at `192.168.4.48:11434` (the GPU
  workstation, flat network, no VLAN segmentation currently in place).
  Verified via `curl http://192.168.4.48:11434/api/tags`.
- **Model: `llama3.2:latest` (3.2B params, Q4_K_M quantization)** — already
  the right size for this task per ADR-005 (small, fast, structured-output
  focused, not a large general-purpose model). Its capability list
  explicitly includes `tools`, meaning native support for structured
  JSON/function-calling output.

## Open questions for next session
- Rate limiting / abuse handling for the public-facing custom question input,
  since this is genuinely a public site now

## v1 shipped — real status

- `/ask` and `/ask/team-form` endpoints live, tested against real Ollama
  output, with 3 real bugs found and fixed through live testing (see git
  history for `api/main.py`)
- `/petey` page live with both modes (Prediction Accuracy, Team Recent Form)
- **Not yet deployed to production** — only tested locally so far.
  `requirements-api.txt` needs `requests`/`pydantic` added, and
  `FUTBOL_OLLAMA_URL` needs to be added to the k3s secret, before the
  next production rebuild/redeploy.

## v2 ideas (deliberately deferred, not open questions)

- **Floating "Ask Petey" button + side drawer**, available from any page
  (not just `/petey`) — same functionality as the current full page, but
  accessible as a persistent widget rather than requiring navigation away
  from what the user is looking at. The full `/petey` page can stay as-is;
  this would be an additional, more discoverable entry point layered on
  top of the same backend.
- Multi-turn conversation (ADR-009) — v1 is deliberately stateless
- True free-text natural-language input, translated into the same
  validated JSON shape (ADR-003) — v1 is UI-driven only, by design
- **Petey as an agent** — autonomous multi-step tool chaining (e.g.
  "compare Seattle's and Portland's corners form, then tell me which the
  model's been more accurate on" — a single question requiring several
  underlying lookups combined, not one fixed shape). Deliberately shelved,
  not scoped yet. Worth flagging explicitly: this is a genuinely larger
  step than v1's single-shot Q&A, not just "v1 plus more question types."
  Multi-step tool chaining is a materially different risk surface than
  ADR-002/003's single-shot pattern — needs its own safety design (call
  limits, loop prevention, validating every step of a chain rather than
  one fixed lookup) before being built, not an assumption that the
  existing allowlist/validator approach extends automatically.

## Resolved design decisions

See docs/adr/petey-decisions.md for the full set of architectural
decision records (ADR-001 through ADR-011), covering the query-builder
approach, timeouts, honesty thresholds, and every other locked-in design
choice with full context and rationale.
