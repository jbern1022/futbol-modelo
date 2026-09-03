I built a calibration fix for my soccer prediction model.

It was correct. It was tested against held-out data. It was merged.

It also silently never ran in production — for weeks.

Here's what happened: my props models predict things like "corners over 5.5" as a raw Poisson probability, which is a well-known liar — a model that's never been checked against reality will confidently tell you 73% when reality says closer to 55%. The fix is isotonic calibration: fit a second, simple model whose only job is "given this said 73%, how often was it actually right?" — and report that number instead.

I built it. It worked. Every test passed.

What I hadn't done was open the actual file my nightly pipeline runs and check, line by line, what it imports. The real slate generator had its own separate code path — refit from scratch every night, never once touching the calibrator I'd written. The site looked fine. Predictions looked plausible. Nothing was obviously broken. If you'd asked me "is the calibration wired in," I'd have said yes — correctly remembering that I built it, tested it, and merged it. Those just aren't the same claim as "this runs in production tonight."

Once it was actually wired in: MLS corners predictions now state an average confidence of 44.5% and realize a 47.5% hit rate. That gap is honest — a handful of points on hundreds of predictions is what real calibration looks like. The bug wasn't "some gap exists." It was a raw model silently overstating its own confidence, indefinitely, with nothing checking it.

The lesson isn't "write more tests." It's narrower: a fix isn't shipped because you wrote, tested, and merged it. It's shipped when it's in the exact function the thing running in production actually calls tonight.

Full writeup: https://futbol.josephbernal.com/lessons-learned
Live calibration tracker: https://futbol.josephbernal.com/track-record
Repo: https://github.com/jbern1022/futbol-modelo
