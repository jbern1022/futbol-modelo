# Petey — Architectural Decision Records

Each entry follows the standard ADR format: Context, Decision,
Consequences. Numbered sequentially; once accepted, a decision is not
edited in place — a later ADR supersedes it and says so explicitly.

---

## ADR-001: Rename "Betting Buddy" to "Petey"

**Status:** Accepted

**Context:** The original working name tied the feature explicitly to
gambling, which doesn't serve a public portfolio project and isn't
actually what the feature does (it's a stats/analytics assistant, not a
wagering tool).

**Decision:** Rename to "Petey," after Peter Brand (Jonah Hill's character
in *Moneyball*, based on Paul DePodesta) — the analyst who trusted the
numbers over the scouts' gut. Fits the project's existing calibration/
honesty identity.

**Consequences:** All code, tables, and copy use "Petey," not "Betting
Buddy" or "Stats Buddy," from the first commit onward.

---

## ADR-002: Ollama's role is strictly bounded

**Status:** Accepted

**Context:** An LLM with open access to write or execute SQL against a
public-facing database is a real security and correctness risk —
hallucinated queries, injection, or simply wrong results presented
confidently.

**Decision:** Ollama never writes SQL and never sees the database schema.
It has exactly one job in v1: turn a final, pre-computed aggregate number
into a conversational sentence. Query construction is handled entirely by
deterministic backend code (see ADR-003).

**Consequences:** Safety comes from the architecture, not from trusting
model behavior. Even a compromised or "jailbroken" model output can't
reach the database in a way that matters, because it's never given the
means to.

---

## ADR-003: Custom "ask" is a UI query builder, not free-text-to-LLM, for v1

**Status:** Accepted

**Context:** A free-text box that gets translated into a query by an LLM
is more flexible but reintroduces real injection/hallucination risk, even
with output validation — the model still has to correctly resist
adversarial input every time.

**Decision:** v1's "ask your own question" flow is a pure UI query
builder: field, operator, and value are all dropdown/multi-select-driven.
No typing is involved in constructing a query at all. This structurally
eliminates the injection surface rather than mitigating it — Ollama never
receives user-typed text intended to become a query.

**Consequences:** v1 is less flexible than open natural-language input,
but categorically safer. True free-text NL input, translated into the
same validated JSON shape, is deferred to v2 — built on top of this
foundation, not instead of it.

---

## ADR-004: Value inputs use type-appropriate controls

**Status:** Accepted

**Context:** Not all fields have the same shape. A single dropdown style
doesn't fit both a fixed 4-value field and an 80-team roster.

**Decision:**
- Fixed-cardinality fields (`market`, `league`, `outcome`) → simple dropdown
- `team` → searchable/autocomplete select (80+ teams across 4 leagues)
- Numeric fields (`avg_stated_prob`, `hit_rate`, `n_predictions`) → range
  slider or min/max inputs with hard bounds (e.g. probability clamped to
  0-1) — never free-text number entry

**Consequences:** More UI components to build than one generic dropdown,
but each is safer and more usable for its actual data shape.

---

## ADR-005: Response timeout thresholds

**Status:** Accepted

**Context:** Ollama runs on homelab hardware, not a latency-guaranteed
paid API. Users need clear expectations rather than an indefinite hang.

**Decision:** Target under 3s for typical responses. Up to 10s is
acceptable UX with a visible "thinking" indicator. 20s is a hard cutoff —
past that, abort and show a graceful fallback message, never a hang or raw
error. Use a small, fast model suited to narrow structured-output tasks,
not a large general-purpose one.

**Consequences:** May need to tune the specific model/prompt if real-world
latency runs higher than expected in testing.

---

## ADR-006: Row/date limit strategy, split by direction

**Status:** Accepted

**Context:** "Recent" means different things depending on direction. A
fixed day-window is inconsistent for backward-looking questions (a quiet
week vs. a busy stretch returns wildly different result counts), but is
the natural fit for forward-looking ones.

**Decision:**
- Backward-looking questions (recent form, head-to-head) → last **10
  games** (row limit, not a date window)
- Forward-looking questions (upcoming predictions) → reuse the app's
  existing day-window convention (21/45 days, matching `auto_slate`)

**Consequences:** Two different limiting mechanisms in one feature, but
each matches how users actually think about "recent" vs. "upcoming."

---

## ADR-007: Small-sample honesty threshold

**Status:** Accepted

**Context:** Honesty is meant to be this project's actual differentiator,
not a slogan. A prediction market with only 2-3 graded results shouldn't
be presented with the same confidence as one with hundreds.

**Decision:** Build one shared small-sample disclaimer component (e.g.
"based on only 4 predictions — treat this cautiously"), triggered whenever
`n < 5`. Reuse it identically in Petey's answers and the Track Record page
— same trigger, same copy pattern, both places. Start at `n < 5` to ship
the feature sooner; revisit raising the threshold to `n < 10` once there's
real usage data to validate against.

**Consequences:** The threshold is a deliberately provisional choice, not
a final one — expected to change based on real feedback, not guesswork.

---

## ADR-008: Conversational responses receive aggregates only, never raw rows

**Status:** Accepted

**Context:** If Ollama's "phrase this conversationally" step is given raw
database rows, it could reference details never actually verified as
correct or relevant to the question — inventing texture that sounds
specific but isn't grounded.

**Decision:** That step receives only the final, pre-computed aggregate
answer — never raw rows. It can only rephrase the one true number it was
handed.

**Consequences:** Responses are less narratively rich than they could be
with full row access, but structurally cannot fabricate extra detail.

---

## ADR-009: v1 is stateless

**Status:** Accepted

**Context:** Multi-turn conversation (referencing a prior question) adds
real complexity — context management, ambiguity resolution — without
being necessary for the feature's core value.

**Decision:** Each question in v1 is independent, with no conversation
memory. Multi-turn is a deliberately deferred v2 idea.

**Consequences:** Users can't ask natural follow-ups like "what about last
month?" in v1 — each question must be fully self-contained.

---

## ADR-010: Presets are pure UI, zero LLM involvement

**Status:** Accepted

**Context:** A preset button click already fully determines its query —
routing it through an LLM would add latency and risk for zero benefit.

**Decision:** Preset "Common Questions" map directly to fixed,
hand-written parameterized queries. Ollama is never invoked for these.

**Consequences:** None of real note — this is a straightforward win with
no tradeoff.

---

## ADR-011: Transparency via inline stat + link, not a full table

**Status:** Accepted

**Context:** Embedding a full data table in every chat response would
make the interface feel cluttered and heavy fast.

**Decision:** Default response shape is a conversational sentence plus a
compact stat line (e.g. "n=14, 57.1% hit rate"), linking to the relevant
filtered Track Record view for anyone who wants the full breakdown.

**Consequences:** Full detail is always one click away, but not
duplicated inline every time — keeps the chat interface light while
staying fully honest.
