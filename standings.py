"""
Shared standings maths.

Before this module, seven endpoints each re-derived "who won and how many points"
by comparing raw scores. That logic now lives in two functions:

  * load_match_entries()  - fetch matches with their two recorded scores
  * compute_team_stats()  - turn them into per-team stats, using the outcome rules
                            in match_outcomes.py to decide winners and points

Endpoints still choose their own grouping (by round, by pool, overall) and their own
ranking keys, but none of them decides a winner on its own any more.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, Hashable, Iterable, List, Optional, Tuple

from match_outcomes import MatchResult, get_rule
from models import Match, Score

# A match plus its two recorded scores (team1_score, team2_score).
MatchEntry = Tuple[Match, int, int]

SKIP_MISSING_SCORES = 'skip'   # match needs both score rows to be counted (old SQL JOIN behaviour)
ZERO_MISSING_SCORES = 'zero'   # a missing score row counts as 0


@dataclass
class TeamStats:
    team_id: str
    matches_scheduled: set = field(default_factory=set)  # every match the team is in
    matches_played: set = field(default_factory=set)     # matches that count (played or decided)
    matches_won: int = 0
    points_scored: int = 0
    points_lost: int = 0

    @property
    def matches_lost(self) -> int:
        # Kept as before: a counted match that was not won (including a tie) is a loss.
        return len(self.matches_played) - self.matches_won

    @property
    def points_difference(self) -> int:
        return self.points_scored - self.points_lost


def load_match_entries(tournament_id, round_id=None, missing_scores: str = SKIP_MISSING_SCORES
                       ) -> List[MatchEntry]:
    """Matches of a tournament (optionally one round) with their recorded scores.

    With SKIP_MISSING_SCORES, a match missing a score row is left out, unless its
    outcome does not use scores at all (e.g. a walkover still counts).
    """
    query = Match.query.filter(Match.tournament_id == tournament_id)
    if round_id is not None:
        query = query.filter(Match.round_id == str(round_id))
    matches = query.order_by(Match.id).all()
    if not matches:
        return []

    scores = Score.query.filter(Score.match_id.in_([m.id for m in matches])).all()
    score_lookup: Dict[Tuple[int, str], int] = {}
    for s in scores:
        score_lookup.setdefault((int(s.match_id), s.team_id), s.score)

    entries = []
    for match in matches:
        s1 = score_lookup.get((match.id, match.team1_id))
        s2 = score_lookup.get((match.id, match.team2_id))
        if (s1 is None or s2 is None) and missing_scores == SKIP_MISSING_SCORES \
                and get_rule(match.outcome).accepts_scores:
            continue
        entries.append((match, s1 or 0, s2 or 0))
    return entries


def compute_team_stats(entries: Iterable[MatchEntry],
                       group_by: Optional[Callable[[Match], Hashable]] = None
                       ) -> Dict[Hashable, Dict[str, TeamStats]]:
    """Per-team stats, grouped by `group_by(match)` (one group, key None, if omitted).

    Every team in a scheduled match gets an entry; only matches the outcome rules say
    count (played, or decided without play) add wins and points.
    """
    groups: Dict[Hashable, Dict[str, TeamStats]] = {}
    for match, team1_score, team2_score in entries:
        key = group_by(match) if group_by else None
        teams = groups.setdefault(key, {})
        for team_id in (match.team1_id, match.team2_id):
            teams.setdefault(team_id, TeamStats(team_id)).matches_scheduled.add(match.id)

        result: MatchResult = get_rule(match.outcome).resolve(match, team1_score, team2_score)
        if not result.counted:
            continue

        t1, t2 = teams[match.team1_id], teams[match.team2_id]
        t1.matches_played.add(match.id)
        t2.matches_played.add(match.id)
        t1.points_scored += result.team1_points
        t1.points_lost += result.team2_points
        t2.points_scored += result.team2_points
        t2.points_lost += result.team1_points
        if result.winner_team_id in teams:
            teams[result.winner_team_id].matches_won += 1
    return groups
