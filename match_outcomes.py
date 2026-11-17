"""
Match outcomes: the single source of truth for HOW a match can be decided.

A match has two separate pieces of state:

  * `match.status`  - lifecycle: pending -> on-going -> completed  (unchanged)
  * `match.outcome` - how a finished match was decided: normal, walkover, ...

Every outcome is described by one `OutcomeRule` below. Code elsewhere never checks
`if outcome == 'walkover'`; it asks the rule instead:

  * standings / promotion  -> rule.resolve(...)            (who won, does it count, points)
  * declaring an outcome   -> rule.validate_declaration()  (is this request allowed)
  * score entry            -> rule.accepts_scores           (can a referee type a score)
  * API / UI               -> rule.describe(match)          (label shown to users)

Adding a new outcome (e.g. forfeit) = adding one entry to OUTCOME_RULES.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

NORMAL = 'normal'
WALKOVER = 'walkover'

# Where the winner of a match comes from.
WINNER_FROM_SCORE = 'score'        # higher recorded score wins
WINNER_DECLARED = 'declared'       # an official names the winner (no play needed)

# Team ids used as bracket placeholders before a team is known.
PLACEHOLDER_TEAM_IDS = {None, '', 'TBD'}


@dataclass(frozen=True)
class MatchResult:
    """The scoring-relevant result of one match, independent of how it was decided."""
    outcome: str
    counted: bool                     # include in standings (played, or decided without play)
    winner_team_id: Optional[str]     # None for ties or undecided matches
    team1_points: int
    team2_points: int


@dataclass(frozen=True)
class OutcomeRule:
    key: str
    label: str                        # shown as a tag in the UI, e.g. "Walkover"
    short_label: str                  # shown in place of a score, e.g. "W/O"
    winner_source: str                # WINNER_FROM_SCORE or WINNER_DECLARED
    accepts_scores: bool              # may a referee enter rally scores for this match?
    # (winner_points, loser_points) awarded instead of recorded scores; None = use recorded scores
    awarded_points: Optional[Tuple[int, int]] = None
    description: str = ''

    @property
    def is_declarable(self) -> bool:
        """Can this outcome be set through the declare-outcome API?"""
        return self.winner_source == WINNER_DECLARED

    def resolve(self, match, team1_score: int, team2_score: int) -> MatchResult:
        """Turn a match plus its recorded scores into a scoring result."""
        team1_score = team1_score or 0
        team2_score = team2_score or 0

        if self.winner_source == WINNER_FROM_SCORE:
            # Existing behaviour, kept exactly: a 0-0 match has not been played yet,
            # and the higher score wins (equal scores = counted, no winner).
            if team1_score == 0 and team2_score == 0:
                return MatchResult(self.key, False, None, 0, 0)
            if team1_score > team2_score:
                winner = match.team1_id
            elif team2_score > team1_score:
                winner = match.team2_id
            else:
                winner = None
            return MatchResult(self.key, True, winner, team1_score, team2_score)

        # WINNER_DECLARED: decided by an official, counts once it is final.
        winner = match.winner_team_id
        if not (match.is_final and winner in (match.team1_id, match.team2_id)):
            return MatchResult(self.key, False, None, 0, 0)

        if self.awarded_points is None:
            team1_points, team2_points = team1_score, team2_score
        else:
            win_pts, lose_pts = self.awarded_points
            team1_points = win_pts if winner == match.team1_id else lose_pts
            team2_points = win_pts if winner == match.team2_id else lose_pts
        return MatchResult(self.key, True, winner, team1_points, team2_points)

    def validate_declaration(self, match, winner_team_id: Optional[str]) -> Optional[str]:
        """Return an error message if this outcome cannot be declared on `match`, else None."""
        if not self.is_declarable:
            return f"Outcome '{self.key}' is decided by scores and cannot be declared"
        if match.team1_id in PLACEHOLDER_TEAM_IDS or match.team2_id in PLACEHOLDER_TEAM_IDS:
            return 'Both teams must be known before an outcome can be declared'
        if match.is_final:
            return 'Match is already finalized'
        if winner_team_id not in (match.team1_id, match.team2_id):
            return 'winner_team_id must be one of the two teams in this match'
        return None

    def describe(self, match=None) -> dict:
        """API representation, so clients never need their own copy of these rules."""
        data = {
            'type': self.key,
            'label': self.label,
            'short_label': self.short_label,
            'decided_without_play': not self.accepts_scores,
        }
        if match is not None:
            data['reason'] = match.outcome_reason
            data['decided_by'] = match.outcome_decided_by
            data['decided_at'] = (
                match.outcome_decided_at.isoformat() if match.outcome_decided_at else None
            )
        return data


OUTCOME_RULES = {
    NORMAL: OutcomeRule(
        key=NORMAL,
        label='Played',
        short_label='',
        winner_source=WINNER_FROM_SCORE,
        accepts_scores=True,
        description='Match was played; the higher score wins.',
    ),
    WALKOVER: OutcomeRule(
        key=WALKOVER,
        label='Walkover',
        short_label='W/O',
        winner_source=WINNER_DECLARED,
        accepts_scores=False,
        # No games were played, so no points either way. This keeps point differential
        # honest (USA Pickleball tiebreakers use point differential of games played).
        awarded_points=(0, 0),
        description='Opponent did not show up; the present team is awarded the win.',
    ),
    # Future outcomes are one entry each, for example:
    # 'forfeit': OutcomeRule(key='forfeit', label='Forfeit', short_label='FF',
    #                        winner_source=WINNER_DECLARED, accepts_scores=False,
    #                        awarded_points=None),  # keep the score at the time of forfeit
}


def get_rule(outcome_key: Optional[str]) -> OutcomeRule:
    """Rule for a stored outcome. Missing/unknown values fall back to normal play."""
    return OUTCOME_RULES.get(outcome_key or NORMAL, OUTCOME_RULES[NORMAL])


def resolve_match(match, team1_score: int, team2_score: int) -> MatchResult:
    """Scoring result for a match, whatever its outcome."""
    return get_rule(match.outcome).resolve(match, team1_score, team2_score)


def describe_outcome(match) -> dict:
    return get_rule(match.outcome).describe(match)
