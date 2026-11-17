# Khel Club v0: Walkover match outcome

This branch adds a new match outcome, **Walkover**, to the Khel Club pickleball tournament
system, across the Flask backend (this repo) and the Next.js frontend
([v0_frontend](https://github.com/2005lakshya/khelclub_v0_frontend), branch `feature/walkover-outcome`).

A walkover means one team did not show up, so the other team is awarded the match without play.

**Contents**

1. [Running it locally](#1-running-it-locally)
2. [How scoring worked before this change](#2-how-scoring-worked-before-this-change)
3. [What I changed and why](#3-what-i-changed-and-why)
4. [Schema and migration](#4-schema-and-migration)
5. [API](#5-api)
6. [Assumptions](#6-assumptions)
7. [How I tested it](#7-how-i-tested-it)
8. [What I would improve with more time](#8-what-i-would-improve-with-more-time)

---

## 1. Running it locally

```bash
# MySQL 8 in Docker, then load the provided dump
docker run -d --name khelclub-mysql -e MYSQL_ROOT_PASSWORD=khelclub -e MYSQL_DATABASE=khelclub -p 3306:3306 mysql:8.0
grep -v "GTID_PURGED\|SQL_LOG_BIN" dump-test-202512221924.sql | docker exec -i khelclub-mysql mysql -uroot -pkhelclub khelclub

# .env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=khelclub
DB_NAME=khelclub

# Python deps, migration, server (port 5001)
python -m venv venv && venv/Scripts/pip install -r requirements.txt   # venv/bin on macOS/Linux
venv/Scripts/python migrations/v2/add_match_outcome.py
venv/Scripts/python app.py

# Tests
venv/Scripts/python -m unittest discover tests
```

The two `GTID`/`SQL_LOG_BIN` lines are removed from the dump because they fail on a fresh MySQL server.

Frontend: `npm install --legacy-peer-deps && npm run dev` (the bracket library has an old peer dependency).
On `localhost` the frontend talks to `http://localhost:5001`.

---

## 2. How scoring worked before this change

### Data

| Table | Role in scoring |
|---|---|
| `match` | Two teams, `round_id`, `pool`, `status` (`pending` / `on-going` / `completed`), `is_final`, `winner_team_id`, and bracket links (`predecessor_1/2`, `successor`) for knockouts. |
| `score` | One row **per team per match** with that team's points (`score`). Rows are created at 0-0 when a match is created. |

### Recording a result

1. The referee screen sends `POST /update-score` with `"11-7"`. Both `score` rows are updated.
2. If `final` is true, the match gets `is_final = true` and `winner_team_id` = the higher score.
   In a knockout the winner is copied into the `successor` match.
3. A `score_update` event is pushed over Socket.IO (namespace `/scores`) for live screens.
4. The frontend separately calls `POST /update-match-status/<id>` with `completed`.

### Standings: the important part

Almost nothing reads `winner_team_id`. Instead, **seven** places re-derived the result from raw scores,
each with its own copy of the logic:

| Code | Used for | How it ranked |
|---|---|---|
| `/standings/<id>` | Pool standings page | wins × 2, then point difference |
| `/overall-standings/<id>` | Overall leaderboard | wins × 2, win %, point difference |
| `/second-place-standings/<id>` | Best second-placed teams | same as above, round 1 only |
| `get_round_standings` (`/complete-round`) | Promoting teams to the next round | wins, then point difference |
| `get_cumulative_points_for_round` (`/create-round`) | Picking the top N teams | **raw points**, then point difference |
| `get_pool_standings` (`/knockout-top-teams`) | Seeding knockouts | wins, then point difference |
| `/complete-round-2` | Elimination promotion | **raw points** |

The shared rules hidden in those copies were:

- higher score = win; equal non-zero scores = played, no winner (counted as a loss in `matches_lost`);
- **a 0-0 match = "not played yet"**, so it is skipped.

That last rule is why a walkover could not simply be stored as 0-0 with a winner: every standings
view would ignore the match, and the winner would get no credit. Storing a fake 11-0 instead would
give the winner points nobody scored, which distorts point difference, the main tiebreaker.

---

## 3. What I changed and why

### Design in one picture

```
match.status   = lifecycle      pending -> on-going -> completed     (unchanged)
match.outcome  = how it ended   normal | walkover | (forfeit, bye, ... later)

                 match_outcomes.py  (the rule book: one OutcomeRule per outcome)
                        |
        +---------------+-------------------+----------------------+
        |               |                   |                      |
  standings.py     POST /matches/<id>/  /update-score        API responses
  (all 7 views)    outcome              (refuses scores       (outcome label,
                   (validation)          on a walkover)        shown by the UI)
```

### Backend

**`match_outcomes.py`: the rule book.** Each outcome is one `OutcomeRule` describing:

| Field | normal | walkover |
|---|---|---|
| `winner_source` | `score` (higher score wins) | `declared` (an official picks the winner) |
| `accepts_scores` | yes | no (no games were played) |
| `awarded_points` | use recorded scores | `(0, 0)` |
| `label` / `short_label` | Played / – | Walkover / W/O |

The rule has the behaviour, so no other code checks `if outcome == 'walkover'`:

- `rule.resolve(match, s1, s2)` → `MatchResult(counted, winner_team_id, team1_points, team2_points)`
- `rule.validate_declaration(match, winner)` → error message or `None`
- `rule.describe(match)` → the JSON the frontend displays

The normal rule reproduces the old behaviour exactly, including "0-0 = not played yet".

**`standings.py`: one place for standings maths.** `load_match_entries()` fetches matches with their
two scores, and `compute_team_stats(entries, group_by=...)` turns them into per-team stats
(played, won, points for/against) by asking each match's rule. All seven views above now call it.
Each view still chooses its own grouping (round, pool, overall), output fields and sort order,
so their responses are unchanged. They just no longer decide winners themselves.

**`POST /matches/<id>/outcome`: declaring a walkover.** One request does everything, inside one
transaction: validate against the rule, set `outcome`, reason, who and when, set the winner, mark
the match `completed` and final, store the awarded points in the `score` rows (so simple point-sum
reports agree with the standings), advance the winner in a knockout, and emit the usual
`score_update` socket event. It is generic: it accepts any outcome whose rule is declarable.

**Guards**

- Can't declare an outcome on a match that is already final (409), on unknown teams, or with a winner
  who isn't in the match.
- `/update-score` refuses scores for a match decided without play (409).
- `/update-match-status` refuses to reopen such a match (409).
- The DUPR rating export skips walkovers: there were no games to rate.

**Also returned to clients:** `outcome` is added to `/get-match-fixtures` (under `match_status`),
`/match-ops/pools/<pool>/fixtures`, and `/score/match`. The fixtures CSV shows `Walkover (winner: T002)`.
`GET /match-outcomes` lists the outcome types.

### Frontend

- **`src/components/matchOutcome/`** is the only place that knows about outcomes:
  - `outcome.js`: helpers that read the backend's `outcome` object (`displayScore`, `resultText`, ...).
  - `OutcomeTag.js`: an MUI `Chip` with the backend's label, and a tooltip with the reason.
  - `DeclareOutcomeDialog.js`: pick the winning team, add a reason, confirm.
  - `useDeclarableOutcomes()`: loads `GET /match-outcomes`. The UI shows a button per declarable
    outcome, so adding "forfeit" in the backend makes a "Forfeit" button appear with no frontend change.
- **Referee match screen:** "Declare Walkover" in the *Match Not Started* dialog (a no-show is noticed
  before play) and in the action bar. A decided match shows "X won by walkover" and the reason
  instead of the score form, with no "Override Score".
- **Everywhere matches are listed** (referee cards, public fixtures, both brackets, pool fixtures,
  court management, both match tables): `W/O` in place of the score, a **Walkover** tag, and the
  winner highlighted with the existing winner style. The public fixture cards didn't highlight
  winners before; they now reuse the referee view's existing `winner` class.

### Options I considered

| Option | Why not |
|---|---|
| Store a walkover as a fake score (11-0) | Invents points, skews point difference, and is a one-off hack. |
| Add `walkover` as a `status` value | Mixes "where the match is" with "how it ended". A bye or forfeit wouldn't fit either. |
| Per-team `result`/`forfeited` columns on `score` | Handles double forfeits, but stores the winner in two places that can disagree. |
| Separate `match_result` history table | Good for auditing and undo, but heavier than needed now. The decided-by/at columns cover the basics. |
| Outcome rules stored in a DB table | Rules like "bye has one team" still need code, so this adds complexity without removing code. |

**Chosen:** an `outcome` column plus rules in code. It is the smallest change that keeps state,
outcome and scoring separate and puts the logic in one place.

### Pre-existing issues found along the way

- **Fixed:** `/create-round` with `num_of_top_teams_to_promote` crashed, because it called `.get_json()` on a
  `(response, status)` tuple. It's on the promotion path this work touches.
- **Not fixed, noted:**
  - The referee UI saves the score and the status in two separate requests.
  - `override` on `/update-score` is accepted but ignored.
  - `update_successor_match` can create `score` rows for `"TBD"` teams.
  - Two promotion paths rank by raw points while the others rank by wins.

---

## 4. Schema and migration

`migrations/v2/add_match_outcome.sql` (and an idempotent Python runner `add_match_outcome.py`,
following the existing `migrations/bul` style; rollback in `add_match_outcome_down.sql`):

```sql
ALTER TABLE `match`
ADD COLUMN `outcome` VARCHAR(20) NOT NULL DEFAULT 'normal',
ADD COLUMN `outcome_reason` VARCHAR(255) NULL,
ADD COLUMN `outcome_decided_by` VARCHAR(100) NULL,
ADD COLUMN `outcome_decided_at` DATETIME NULL;
```

- Existing rows become `normal`, so nothing changes for them.
- `VARCHAR`, not `ENUM`: valid values are defined once, in `match_outcomes.py`, so a new outcome
  needs no migration. An unknown stored value is treated as `normal`.
- The `score` table is unchanged. A walkover's rows are kept at 0-0, so existing joins still see the match.

---

## 5. API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/match-outcomes` | Outcome types: `type`, `label`, `short_label`, `declarable`, `decided_without_play`. |
| `POST` | `/matches/<id>/outcome` | Body: `{ "outcome": "walkover", "winner_team_id": "T002", "tournament_id": 1, "reason": "...", "decided_by": "referee" }` |

Responses: `200` with the updated match and its `outcome`; `400` for an unknown outcome or an invalid
winner; `404` for an unknown match; `409` if the match is already final.

---

## 6. Assumptions

- **A walkover is a win with 0 points for both teams.** No games were played, so no points either way.
  This keeps point difference honest. USA Pickleball's second round-robin tiebreaker is
  "point differential of all games played" (rule 15.B.4.c). It's one setting (`awarded_points`)
  if an organiser prefers e.g. 11-0.
- **A walkover counts as a match played** for both teams: a win for one, a loss for the other.
- **Only a match that isn't final can become a walkover.** Corrections (undoing a walkover) are not
  in scope. See below.
- **Both teams must be known.** Knockout placeholders (`TBD`) can't be walked over yet.
- **No authentication exists in v0**, so `decided_by` is a free-text label (the UI sends `"referee"`).
- **Withdrawing from a whole event is different from a single walkover.** USA Pickleball removes all of
  a withdrawn team's results (rule 15.B.4.a). That would be its own outcome or feature.

---

## 7. How I tested it

1. **Normal matches unchanged.** Before touching any code, I entered real scores through the existing
   API and saved the output of all six standings/ranking views. After the refactor the output was
   **byte-for-byte identical**. `/complete-round-2`'s totals were compared separately.
2. **Unit tests** (`tests/test_match_outcomes.py`, 15 tests, no DB): normal results, 0-0, ties,
   walkover win and points, validation, and standings with a mix of outcomes.
3. **API checks:**
   - unknown outcome → 400; winner not in match → 400; already-final match → 409;
     wrong tournament → 404
   - valid walkover → 200; declaring twice → 409; entering a score afterwards → 409;
     reopening → 409; normal scoring still works
4. **Standings after a walkover:** only the two teams involved changed. The winner gained a win and a
   match played, its point difference stayed the same, and the ranking reordered as expected.
5. **UI, end to end:** declared a walkover from the referee screen, then checked the referee cards, the
   table, the public fixtures and the standings.

**Demo for the screen recording:** reload the dump, run the migration, then open
`/referee/1/matches/11`, choose **Declare Walkover**, pick the team that showed up, and confirm.
Then show `/referee/1/matches` (cards and Table) and `/tournament/1` (Fixtures and Standings).

---

## 8. What I would improve with more time

- **Undo / correct an outcome** (USA Pickleball rule 15.G allows error corrections), including clearing a
  knockout winner that was already advanced.
- **Forfeit and bye.** Forfeit is one rule entry (`awarded_points=None` keeps the score at the time of
  forfeit). A bye needs matches with a single team, so knockouts work without a power-of-two team count.
- **Authentication**, so `decided_by` is a real user and only officials can declare outcomes.
- **One request for score + status** on the referee screen, so a match can't end up half-updated.
- **Make the remaining raw-point views** (`/points`, `/points/pool`, reports) use the shared stats, and agree
  on one ranking rule across promotion paths.
- **Integration tests** against a test database, and replacing debug `print`s with logging.

---

## Pool pairing reference (existing)

| **# Pools** | **Same-Pool Pairing**                        | **Near-pool Pairing**                       | **Half-Pool Pairing**                     | **Far-Pool Pairing**                     |
|-------------|----------------------------------------------|---------------------------------------------|-------------------------------------------|------------------------------------------|
| **2 Pools** | A1 vs A2, B1 vs B2                           | A1 vs B2, A2 vs B1                         | A1 vs A2, B1 vs B2 (same as "same-pool")  | A1 vs B2, A2 vs B1                       |
| **4 Pools** | A1 vs A2, B1 vs B2, C1 vs C2, D1 vs D2       | A1 vs B2, A2 vs B1, C1 vs D2, C2 vs D1     | A1 vs B2, A2 vs B1, C1 vs D2, C2 vs D1    | A1 vs D2, A2 vs D1, B1 vs C2, B2 vs C1   |
| **8 Pools** | A1 vs A2, B1 vs B2, C1 vs C2, D1 vs D2, E1 vs E2, F1 vs F2, G1 vs G2, H1 vs H2 | A1 vs B2, A2 vs B1, C1 vs D2, C2 vs D1, E1 vs F2, E2 vs F1, G1 vs H2, G2 vs H1 | A1 vs D2, A2 vs D1, E1 vs H2, H1 vs E2    | A1 vs H2, A2 vs H1, B1 vs G2, B2 vs G1, C1 vs F2, C2 vs F1, D1 vs E2, D2 vs E1 |
