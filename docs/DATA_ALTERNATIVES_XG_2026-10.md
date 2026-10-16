# Free alternatives to Understat for shot-level data and team xG (2026-10-15)

**Status:** Research note, not legal advice. Primary sources only; where a
page could not be fetched or read, the cell says "not verified". Fetching
was limited to licence/terms/README/listing pages. No bulk data was
downloaded, no paid API was called, nothing was written to a database.
Many commercial sites (Sports Reference, API-Football, Sofascore terms)
returned 403/404 to the fetch tool, so several answers below are gaps, not
findings.

> **Edits after the research agent's pass (2026-10-15/16, by the project
> owner's assistant, not by the agent):** (1) "three leagues" corrected to
> four in section 5, item 1, because the Bundesliga history was loaded on
> 2026-10-14; (2) the Understat table row and note now point at the direct
> robots.txt and terms check in `docs/DATA_LICENSING.md` (gap 1a). Nothing else
> was changed. Spot check: StatsBomb's `competitions.json` was re-read
> independently and matches the coverage stated here for the Bundesliga,
> Ligue 1, MLS, La Liga, EPL and Serie A. API-Football's terms and docs also
> return 403 to `curl` and the fetch tool, so they remain unread.

## 1. Bottom line

No free source found covers the priority leagues for 2021-22 to 2025-26
with shot-level or team xG under terms that clearly allow a public
prediction site. The only free, openly published shot-level data that was
verified is StatsBomb open data (3 Ligue 1 / Bundesliga seasons in the
priority set, nothing else) and the Wyscout/Pappalardo event set (one
season, 2017-18, of five leagues, none of them a priority league except
Ligue 1 and Bundesliga). Everything else with xG for the priority leagues
(FBref, Understat, FotMob, Sofascore, WhoScored) is a site whose terms or
robots.txt restrict automated access, and the scraper packages (soccerdata,
worldfootballR, ScraperFC) state no terms of their own and point at those
same sites. The most plausible no-purchase path is: use API-Football
`expected_goals` for 2023-24 onwards (already in use), build an in-house xG
model, and treat the missing 2021-22 to 2022-23 xG as a gap rather than
filling it by scraping. Whether API-Football's terms allow publishing
derived predictions is **not verified** (terms page returned 403).

## 2. Comparison table

| Source | Data | Verified leagues / seasons | Licence or terms (quoted) | Public-site use OK? | Attribution | Verdict |
|---|---|---|---|---|---|---|
| Understat (current) | shot-level + team xG | Four leagues loaded: EPL, Serie A, La Liga, Bundesliga (not re-checked in this pass) | robots.txt: `User-agent: *` / `Disallow: /` ([robots](https://understat.com/robots.txt)); no ToS found | Unclear; robots.txt disallows all crawling | None stated | Stop adding leagues (owner decision) |
| StatsBomb open data | shot-level with xG (event data) | Bundesliga 2023/24; Ligue 1 2021/22, 2022/23 (+2015/16); MLS 2023; La Liga up to 2020/21; EPL 2015/16 and 2003/04 only | "If you publish, share or distribute any research, analysis or insights based on this data, please state the data source as StatsBomb and use our logo" ([README](https://github.com/statsbomb/open-data)); LICENSE.pdf titled "StatsBomb Public Data User Agreement", text not readable | Unclear: README wording permits publishing analysis with credit; the PDF was not read | StatsBomb named as source + logo | Adopt for validation only; too thin for training |
| Wyscout events (Pappalardo et al.) | shot-level events (no xG field stated) | One season each of La Liga, Serie A, Bundesliga, EPL, Ligue 1, plus WC 2018, Euro 2016; season years not stated on collection page | Events file: "CC BY 4.0" ([figshare API](https://api.figshare.com/v2/articles/7770599)); collection page "does not state a license" ([collection](https://api.figshare.com/v2/collections/4415000)) | Probably yes for the Events file (CC BY includes commercial), but Wyscout's underlying rights not verified | Cite the Nature Sci. Data paper | Useful only to train an xG model; old data |
| Metrica Sample Data | tracking + events, 3 games | 3 sample games, no league | GitHub licence field `null`; README: "be responsible with the use of this data" ([README](https://raw.githubusercontent.com/metrica-sports/sample-data/master/README.md), [API](https://api.github.com/repos/metrica-sports/sample-data)) | Unclear; no licence | Credit requested | Not useful (3 games) |
| FBref / Sports Reference | team + shot xG historically | Not verified | "without our express written permission, use any automated means to access or use the Site" is prohibited; "Please do not attempt to aggressively spider data from our web sites" ([data_use](https://www.sports-reference.com/data_use.html)); also bars using content to build a competing database and to train AI models | No for scraping, per the terms as read | n/a | Do not use. Whether Opta xG is still published: not verified (fbref.com returned 403) |
| football-data.co.uk | results, odds, shots/corners/cards | Not enumerated | No licence on [notes.txt](https://www.football-data.co.uk/notes.txt); xG not mentioned | Unclear: no terms stated | Sources acknowledged by the site | Results/odds only, no xG |
| football-data.org | fixtures, tables; shots only in paid add-on | Free plan "12 competitions", not listed | Pricing page: xG not mentioned; shots in Statistic Add-On at EUR 15/mo ([pricing](https://www.football-data.org/pricing)); /terms returned 404 | Not verified | Not verified | No xG, not an alternative |
| openfootball | fixtures/results, clubs | Not enumerated | Repos labelled "CC0-1.0" ([org](https://github.com/openfootball)) | Yes (CC0) for the data it has | None | No xG/shots; results only |
| Transfermarkt datasets (dcaribou) | results, lineups, events | Not enumerated | "CC0-1.0 license" on repo ([repo](https://github.com/dcaribou/transfermarkt-datasets)); built from Transfermarkt data, no disclaimer on terms | Unclear: repo licence does not address Transfermarkt's own terms | None | No xG/shots |
| American Soccer Analysis (itscalledsoccer) | team/player/GK xG, MLS and US leagues | mls, nwsl, uslc, usl1, usls, nasl, mlsnp; seasons not verified | Package: "MIT © itscalledsoccer authors"; "The API is free and public — no authentication required." ([README](https://github.com/American-Soccer-Analysis/itscalledsoccer)); ASA terms page 404 | Unclear: data terms not stated | Not stated | Only candidate for MLS xG; terms need a human to check |
| soccerdata (probberechts) | scraper | Lists Understat, FBref, WhoScored, Sofascore, ESPN, etc. | Docs: no disclaimer; "Check each source's own terms" was the fetch tool's summary, not a quote ([docs](https://soccerdata.readthedocs.io/en/latest/)); README 404 | Depends on source | n/a | Not a data source |
| worldfootballR | scraper | FBref, Transfermarkt, Understat | README: "please ensure you attribute the source of the data"; fotmob dropped "due to a change in their terms of service"; repo "will no longer be maintained" ([README](https://raw.githubusercontent.com/JaseZiv/worldfootballR/master/README.md)) | Depends on source | Required by README | Archived; not a source |
| ScraperFC | scraper | Capology, ClubELO, FBref, Sofascore, Transfermarkt, Understat | README states no terms of use ([README](https://raw.githubusercontent.com/oseymour/ScraperFC/main/README.md)) | Depends on source | n/a | Not a source |
| understatapi | scraper | Repo URL 404 | Not verified | Not verified | n/a | Not verified |
| FotMob | match xG (site) | Not verified | robots.txt disallows `/api/*` for all crawlers, allowed for Googlebot, Bingbot etc. ([robots](https://www.fotmob.com/robots.txt)); worldfootballR says fotmob support was dropped over a terms change | No for its API | n/a | Do not use |
| Sofascore | match stats incl. xG (site) | Not verified | Terms page text not retrieved ([page](https://www.sofascore.com/terms-and-conditions)) | Not verified | n/a | Not verified |
| WhoScored | event data (Opta-sourced) | Not verified | robots.txt `User-agent: *` disallows `/accounts/`, `/predictions/`, `/users/` only ([robots](https://www.whoscored.com/robots.txt)); ToS not retrieved | Not verified; robots.txt is not a licence | n/a | Not verified |
| ClubElo | Elo ratings only | n/a | Usage terms not found in the page text read ([clubelo.com/API](http://clubelo.com/API)) | Not verified | Not verified | Not xG; possible side feature |
| API-Football | team xG per match (`expected_goals`), no shot-level | Per the owner's brief: reliable from 2023-24 for most leagues; not independently verified | Docs and terms pages returned 403 | Not verified | Not verified | Keep; confirm terms (already a open gap in DATA_LICENSING.md) |

## 3. Per-source notes

**Understat.** `https://understat.com/robots.txt` reads exactly
`User-agent: *` / `Disallow: /`. I did not find a ToS page in this pass. A direct check on 2026-10-16
(`/terms`, `/privacy`, `/legal`, `/tos`, `/about` all 404; footer has only a
copyright line and a support email) is recorded in `docs/DATA_LICENSING.md`,
gap 1a.
A robots.txt is not a licence, but it is an explicit signal.

**StatsBomb open data.** Competition listing read from
[competitions.json](https://raw.githubusercontent.com/statsbomb/open-data/master/data/competitions.json)
(80 competition-seasons). The README ([source](https://github.com/statsbomb/open-data))
carries one terms line, quoted in the table, and links `LICENSE.pdf`
(file exists per the [repo contents API](https://api.github.com/repos/statsbomb/open-data/contents)).
The PDF is titled "StatsBomb Public Data User Agreement"; its body is an
encoded stream the fetch tool could not decode, so the actual clauses on
commercial use are **not verified**. The earlier project note ("free for
non-commercial/research use") is therefore unconfirmed by this pass. The
README does not say "Data provided by StatsBomb"; it says state the source
as StatsBomb and use their logo (Media Pack: https://statsbomb.com/media-pack/).
Shots with xG exist in the event files in principle; I did not open event
files.

**Wyscout / Pappalardo.** The Events article
([figshare 7770599](https://api.figshare.com/v2/articles/7770599)) says
"CC BY 4.0", 77.3 MB, seven event types including shot, and asks users to
cite Pappalardo and Massucco. The collection page
([4415000](https://api.figshare.com/v2/collections/4415000)) lists La Liga,
Serie A, Bundesliga, Premier League, Ligue 1, FIFA World Cup 2018, Euro
2016, "an entire season" each, and states no licence of its own. Which
season (I believe 2017-18) is not stated on the page: **not verified**.
The paper (Nature Sci. Data 6:236) was behind a login redirect/browser
check, so its data-availability statement was not read. Event data has
shot coordinates, not xG; an in-house model would have to be trained.

**Metrica.** Three games, no licence field; the README's "Legal stuff"
asks users to be responsible and credit the source. Irrelevant at this
scale.

**FBref / Sports Reference.** Terms quoted in the table come from
https://www.sports-reference.com/data_use.html. No numeric rate limit is
given. The page does not mention Opta. fbref.com pages (about, robots.txt)
returned 403, so whether FBref still publishes xG/advanced stats in 2026
is **not verified**. worldfootballR's README says FBref is "partnered with
StatsPerform Opta" (secondary: a scraper author's description).

**football-data.co.uk.** [notes.txt](https://www.football-data.co.uk/notes.txt)
lists shots, shots on target, woodwork, corners, fouls, cards. xG is not
mentioned. No licence text.

**football-data.org.** Free plan: scores/schedules delayed, 10 calls per
minute, no xG, shots only in a paid add-on ([pricing](https://www.football-data.org/pricing)).

**openfootball and Transfermarkt datasets.** Both CC0 at repo level, both
without xG or shots. The Transfermarkt dataset's CC0 label does not settle
Transfermarkt's own rights (flagged, not resolved).

**American Soccer Analysis.** MIT applies to the Python client. The README
says the API is "free and public" and documents team, player and
goalkeeper xG. No data licence was found (terms page 404). Not needed
unless MLS xG becomes a goal; MLS is not a priority league.

**Scrapers.** None of soccerdata, worldfootballR or ScraperFC states terms
for the underlying sites in the pages read, so using them does not change
the legal position of the source site. worldfootballR is archived.

**Own xG model.** Needs freely licensed shot locations. Verified candidates:
StatsBomb open data (agreement text unread) and Wyscout events (CC BY 4.0
on the Events file). Both together cover a few thousand shots per league at
most and none from 2021-26 except Ligue 1 and Bundesliga 2023/24 in
StatsBomb. A generic xG model (distance/angle/body part) trained on them
could be applied to any league that supplies shot coordinates; but no
verified free source supplies 2021-26 shot coordinates for the priority
leagues. API-Football per-shot data was not checked.

## 4. Coverage grid for priority leagues

Legend: V = verified present, - = verified absent in the source listing,
? = not verified.

| League | StatsBomb open | Wyscout open | Free team xG 2021-26 | API-Football xG (brief) |
|---|---|---|---|---|
| Bundesliga | V 2023/24 only (also 2015/16) | one old season, year not stated | none verified | ? 2023-24 on, per brief |
| Ligue 1 | V 2021/22, 2022/23 (also 2015/16) | one old season | none verified | ? as above |
| Eredivisie | - | - | none verified | ? |
| Brasileirao Serie A | - | - | none verified | ? |
| Liga MX | - | - | none verified | ? |
| Championship | - | - | none verified | ? |
| Primeira Liga | - | - | none verified | ? |
| Super Lig | - | - | none verified | ? |
| Argentina Liga Profesional | - (1997/98 and 1981 only) | - | none verified | ? |
| J1 | - | - | none verified | ? |
| Saudi Pro League | - | - | none verified | ? |
| Serie B, 2. Bundesliga, Scottish Prem., Belgian Pro | - | - | none verified | ? |

"-" for Wyscout rests on the collection listing only the five big leagues
and two tournaments. The API-Football column repeats the owner's brief; the
coverage page and docs returned 403.

## 5. Recommended path

1. Freeze Understat at the four leagues already loaded (EPL, Serie A, La Liga
   and, since 2026-10-14, the Bundesliga); do not add more. Keep a note that
   Understat's robots.txt disallows all crawling.
2. Rely on API-Football `expected_goals` (2023-24 on) for new leagues,
   after a human confirms its terms permit publishing derived predictions
   (open gap 4 in DATA_LICENSING.md). Verify per league and season with a
   small, budgeted check of the real API (outside this research pass).
3. For 2021-22 and 2022-23 in new leagues, use a goals-only model (Dixon-Coles
   style, already in the repo) and do not claim xG blending there. This
   loses the xG blend for two of the five seasons in the new leagues.
4. For red-card and in-play calibration, goal minutes are enough (item b in
   the brief); results sources such as openfootball (CC0) or the API-Football
   events already ingested cover that. Whether API-Football's goal-minute
   data is complete for the new leagues is not verified.
5. Rescaling live xG (item c) needs only 2023-24 onward from the same
   provider, so it does not need Understat.
6. Treat StatsBomb Bundesliga 2023/24 and Ligue 1 2021/22-2022/23 as an
   optional validation set once the agreement PDF has been read by a human.
7. If xG for 2021-23 in the priority leagues is genuinely required, that
   still needs a paid provider (quote request, not evaluated here).

**Open questions for a human**
- Read StatsBomb `LICENSE.pdf` for commercial/public-site clauses.
- Read API-Football's terms for derived-prediction publication, caching,
  and attribution.
- Decide whether losing 2021-23 xG in new leagues is acceptable.
- Decide whether to ask Understat's owner for permission (no contact found).
- Check FBref's current data provider and terms in a browser.

## 6. Not verified

- StatsBomb LICENSE.pdf contents; shot xG field in event files.
- Wyscout dataset season years, paper's data-availability statement, any
  Wyscout rights statement beyond figshare's CC BY 4.0.
- API-Football: xG coverage by league/season, terms (403 on all pages).
- FBref: current xG availability and whether Opta data is still shown.
- Sofascore and WhoScored terms; FotMob terms page (robots.txt only).
- ClubElo usage terms; ASA data terms; football-data.org terms (404) and
  free-competition list.
- understatapi repo (404); soccerdata README (404, docs page used).
- Kaggle / GitHub mirrors of Understat or FBref data: not searched, no
  licence checked.
- Opta/Stats Perform terms: not fetched.
- League-run open data: not searched.
- Understat ToS: none found, not exhaustively searched.
