# The UNIQUE constraint that never was

Here's a line of code that looks completely correct, does nothing wrong
syntactically, runs without a single error for as long as you leave it
running, and is still wrong:

```python
def upsert_team(cur, canonical: str) -> int:
    cur.execute(
        """INSERT INTO futbol.teams (name) VALUES (%s)
           ON CONFLICT DO NOTHING""", (canonical,))
    cur.execute("SELECT team_id FROM futbol.teams WHERE name = %s", (canonical,))
    return cur.fetchone()[0]
```

That's the real `upsert_team()` from this project's ingestion layer, as
it existed from the very first commit. It reads like a standard
upsert: insert a team by name, and if it's already there, don't insert
it again. `ON CONFLICT DO NOTHING` is the idiomatic Postgres way to
write that.

Except `teams.name` never had a unique constraint on it. And
`ON CONFLICT DO NOTHING`, written bare with no column list, doesn't
need one to be valid SQL. It just means "if this insert would violate
*some* constraint, skip it" — and if there's no constraint capable of
being violated, there's never a conflict. Every single call to
`upsert_team("Arsenal")` was a plain, unconditional `INSERT`. Every
re-scrape of every match created a brand-new `teams` row with a brand
new `team_id`, forever, for as long as the project had been running.

## Why nothing caught it

This is the part that actually bothers me. Bad SQL usually announces
itself — a syntax error, a type mismatch, a foreign key violation.
This didn't. `ON CONFLICT DO NOTHING` with no target is *legal*
Postgres. It parses. It executes. It returns success. The only
observable difference between "this is deduplicating correctly" and
"this is silently creating a new row every time" is a query you'd have
to think to run:

```sql
SELECT name, COUNT(*) FROM teams GROUP BY name HAVING COUNT(*) > 1;
```

Nobody ran that query until match data started looking wrong — fixture
joins failing to line up, team stats scattered across rows that were
supposed to be the same team but had different surrogate keys. By the
time it was actually investigated, it wasn't a hypothetical: real
fixtures, real predictions, and real per-match stats were already
split across duplicate team identities that had been accumulating
since day one.

## The fix was two lines, the cleanup was not

The actual code fix is almost embarrassingly small:

```diff
- ON CONFLICT DO NOTHING
+ ON CONFLICT (name) DO NOTHING
```

Adding the column list changes `ON CONFLICT DO NOTHING` from "ignore
any conflict" to "specifically expect a conflict on `name`" — which
Postgres will refuse to accept unless a matching unique constraint or
index actually exists. So the real fix was two parts, and the second
one is the one that actually does anything:

```sql
ALTER TABLE teams ADD CONSTRAINT teams_name_unique UNIQUE (name);
```

But you can't just add a unique constraint to a column that already
has duplicates — Postgres will (correctly) refuse. So before that
line could run, every duplicate team had to be merged: pick one
canonical `team_id` per name, repoint every foreign key that pointed
at a duplicate — `matches.home_team_id`, `matches.away_team_id`,
`team_match_stats.team_id`, `player_match_stats.team_id`,
`shots.team_id`, `predictions.subject_team_id` — and only then delete
the now-unreferenced duplicate rows. That's what
[`sql/fix_duplicate_teams.sql`](../../sql/fix_duplicate_teams.sql)
actually does: six `UPDATE` statements re-parenting live data before a
single `DELETE` runs, then the constraint goes on last, as a permanent
guarantee that this specific class of bug can't quietly happen again.

## The bug survived its own fix

Here's the part I didn't expect to find while writing this post. The
constraint went onto the *live* database on 2026-07-10. It never made
it into `sql/schema.sql` — the file that's supposed to describe the
whole schema from scratch. Six weeks later, while writing this exact
writeup, I checked, and `schema.sql`'s `CREATE TABLE teams` still had
no unique constraint on `name` at all.

Which means: the live database has been fine this whole time, but if
anyone had ever rebuilt this project's database from the tracked
schema alone — a disaster recovery, a fresh dev environment, a
teammate cloning the repo — they'd have recreated the exact bug this
story is about, silently, with no error, for the exact same reason
nobody caught it the first time. The fix fixed the database. It never
fixed the description of the database.

That's now fixed too — `schema.sql` has the constraint, and a small
migration (`sql/migrations/0006_track_teams_name_unique.sql`) exists
specifically to be a no-op against the live database while bringing
the tracked schema back in sync with what's actually running. But it's
a genuinely good illustration of the same underlying lesson twice in
one bug: **a fix that isn't checked into the thing everyone actually
reads from isn't really fixed.** The first time, that thing was the
running code. The second time, it was the schema file describing the
running database. Same shape of mistake, one layer further down.

## The actual lesson

`ON CONFLICT` is only as safe as the constraint behind it, and
Postgres will happily let you write the unsafe version without telling
you. If your upsert relies on `ON CONFLICT`, the column list isn't
optional decoration — it's the only thing that turns "ignore silently"
into "verify a real guarantee exists." And whatever guarantee you add
to fix a live incident needs to land in every place someone might
later rebuild that system from — not just the database that's already
running.
