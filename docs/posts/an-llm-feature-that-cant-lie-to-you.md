# An LLM feature that can't lie to you

Petey is a small Q&A feature on top of a soccer prediction site,
backed by Ollama running on a homelab GPU. It answers questions like
"how accurate are your corners predictions?" It also, structurally,
cannot write a SQL query, cannot see the database schema, cannot see a
single raw row of data, and cannot inject an opinion into an answer
that wasn't already true before the model ever saw the question. None
of that is because the model is well-behaved. It's because it was
never given the ability to do otherwise.

That distinction — safety from architecture, not from trusting the
model — is the actual design, and it's worth walking through why each
piece of it exists.

## The model never sees the database

The obvious way to build "ask a question about your data" is: user
types a question, LLM writes SQL, you run the SQL, you show the
result. This is also a genuinely bad idea for anything public-facing.
An LLM generating SQL against a real database is one confidently wrong
query, or one adversarial prompt, away from a real problem — and
"validate the generated SQL before running it" just moves the same
trust problem one step later, since now you're trusting a second model
call (or a hand-rolled parser) to catch every way the first one could
go wrong.

Petey's model never gets the chance. Ollama in this system has exactly
one job: take a number that's already been computed by ordinary,
boring, deterministic backend code, and turn it into one plain-English
sentence. It never sees a schema. It never sees a table name. If you
gave it a prompt injection attack today, the most damage it could do
is phrase a true, pre-computed number in an unusual way — because
that's the only capability it has.

## Free text doesn't mean "let the model build the query"

The current version's "ask your own question" flow looks like a
chatbot, but the query itself is built entirely by dropdown and
autocomplete UI — market, league, outcome, a searchable team picker
for the 80-plus teams across four leagues. No typing is involved in
constructing the actual query at any point. This is a deliberate,
temporary constraint: true free-text natural-language input is
explicitly deferred, and when it does ship, the plan is for it to
compile down into the exact same validated, allowlisted query shape
this version already uses — never a path where the model's raw text
output becomes part of a query directly.

It's a less flexible v1 than an open text box would be. It's also
categorically safer, in a way that doesn't depend on the model
resisting adversarial input correctly every single time it's asked.

## The step that talks to you never sees raw rows

Even the one thing Ollama *is* allowed to do — phrase a result as a
sentence — is scoped tighter than it looks. It receives the final
aggregate only: one number, or a small handful of them. It never
receives the underlying rows that number was computed from. This
matters because an LLM given raw rows to summarize will often add
texture that sounds specific and grounded but isn't actually verified
— a plausible-sounding detail that was never checked against anything.
Handing it only the one true number it's allowed to talk about makes
that failure mode structurally unavailable, not just discouraged.

## Small samples get flagged, the same way, everywhere

Part of the actual differentiator this whole project claims is
honesty about uncertainty, not just about outcomes. A stat computed
from three graded predictions and a stat computed from three hundred
shouldn't be presented with the same confidence. There's one shared
disclaimer component — "based on only 4 predictions, treat this
cautiously" — triggered under the same threshold, with the same
copy, in Petey's answers and on the site's own Track Record page. Not
two versions of the same idea that could quietly drift apart. One.

## Where "trust the model" almost crept back in

Here's the part I think is actually the more useful story, because
it's not about the design — the design above is fine, and was fine
from the start. It's about how close a real gap got to shipping
anyway, despite it.

Ollama's raw phrasing is filtered through a structural check before
it's ever shown to anyone: if the model's sentence contains an
unsupported judgment word — "struggled," "impressive," "steady,"
anything characterizing a plain number as good or bad without a stated
baseline to compare it to — the answer is thrown away entirely and
replaced with a plain, deterministic sentence instead. That's the
correct fix, and it works. It's also, on its own, not the whole story.

Petey has two response modes — a default "accuracy" mode and a
secondary "team form" mode. The judgment-word filter was built once,
correctly, and wired into the team-form mode. It was never actually
called from the accuracy mode — the one that's the default, the one
most visitors hit first. For however long that gap existed, the
*safest* one of Petey's two modes was the one people were least likely
to use. Nothing was visibly broken. The filter existed in the
codebase, tested and working, exactly like the isotonic calibrator in
this project's other "built it, never wired it in" story. It just
wasn't in the one path that mattered most.

The fix was small — one missing function call, added to match the
path that already had it right. The lesson is the same one this whole
project keeps circling back to: a safety mechanism that exists in your
code isn't the same claim as a safety mechanism that's actually in the
way of the thing it's supposed to be protecting. You have to go check
which one you actually built.
