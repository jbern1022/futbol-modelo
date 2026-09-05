# My calibration fix never shipped

I want to describe a specific kind of bug that I think doesn't get
talked about enough, because it doesn't look like a bug at all while
it's happening. No stack trace. No failing test. No incident. Just a
fix that was real, correct, reviewed, and completely absent from
production for weeks — while everyone involved, including me,
believed it was live.

## The actual problem it was supposed to fix

This project's props models — corners, shots on target, that kind of
market — are LightGBM models predicting a Poisson-distributed count,
then converting that into "probability the count is over/under some
line." Raw model output for that kind of prediction is a well-known
liar. A model that's never been checked against reality will hand you
a number like "73% likely" that, over enough repeated bets, comes true
something closer to 55% of the time. Confident, and wrong in a
specific, correctable direction.

The correction for this is isotonic regression: instead of trusting
the model's raw output, you fit a second, much simpler model whose
only job is "given this model said 73%, how often was it actually
right, historically?" — and you report *that* number instead. Done
right, this is what actually makes a stated probability honest rather
than just confident-sounding.

I built this. It lived in `src/models/props.py`. It worked in testing.
It was calibrated correctly, validated against held-out data, and by
every reasonable definition of "done," it was done.

## What "done" actually meant

Here's the real commit message from the fix that eventually corrected
this, months later:

> The slate generator refit a LightGBM model from scratch for every
> fixture and every market. That made predictions unreproducible,
> wrote one meaningless `model_versions` row per fixture
> (`version_tag` was `"{home}_v_{away}_{date}"`, `training_window` was
> the literal string `"live_fit"`), and left nowhere for a calibrator
> to live — so the raw Poisson tail probability was what reached the
> ledger. **The isotonic calibration in `src/models/props.py` was
> never imported by anything.**

That last sentence is the whole story. The calibration module existed.
It was correct. It was never called by the code the real nightly
pipeline actually runs. The live slate generator had its own separate
path that refit a model from scratch for every single fixture, threw
the raw output straight into the prediction ledger, and never once
touched the calibrator that was supposed to sit between "model says"
and "site publishes."

Every prediction the site made during that window was real — locked
before kickoff, graded honestly, published either way, exactly per
the ledger's own rules. It just wasn't calibrated the way I believed
it was.

## Why nothing caught it

This is the part that actually matters, more than the bug itself.
Nothing about the running system looked broken. The site loaded. The
predictions looked plausible — a Poisson tail probability isn't
*obviously* wrong just by eyeballing it, especially for someone who
already believes the calibration layer is in the loop. The commit
history read like a finished feature. If you'd asked me, at the time,
"is the calibration wired in," I would have said yes, correctly
remembering that I built it, tested it, and merged it.

What I hadn't done was open the actual file the CronJob executes and
check, line by line, what it imports. The gap wasn't in the code I
wrote — the calibrator was genuinely correct. The gap was between "I
built this and it works" and "this is in the path that runs in
production, tonight, unattended." Those are two different claims, and
only one of them was ever actually verified.

## What it looks like now that it's real

Isotonic calibration is fit on out-of-fold predictions only — never on
the same data the underlying model trained on, since checking a
model's confidence against data it already memorized just tells you
it's confident, not that it's right. Here's a real, live number from
the site as of writing this: MLS corners predictions currently state
an average confidence of 44.5% and realize a 47.5% hit rate. That's
not a perfect match, and it doesn't need to be — a handful of points
of gap on hundreds of predictions is what an honestly-calibrated model
actually looks like. The failure mode this fix corrected wasn't "some
gap exists." It was a raw, uncorrected model systematically
overstating its own confidence, with nothing checking it, indefinitely.

## The actual lesson

I don't think the lesson here is "write more tests," though tests
help. The lesson is narrower and less comfortable: a fix isn't shipped
because you wrote it, tested it, and merged it. It's shipped when
it's in the exact file, in the exact function, that the thing running
in production actually calls tonight. Those can quietly diverge — a
new pipeline entry point gets built, an old one keeps running, a
"temporary" code path outlives the thing that was supposed to replace
it — and nothing about the system will tell you that happened. It just
sits there, correct and unused, until someone goes and actually reads
the code that runs instead of trusting that it does what the last
commit message said.
