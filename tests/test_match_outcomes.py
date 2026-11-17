"""
Unit tests for the outcome rules and the shared standings maths.
No database needed: matches are simple stand-in objects.

Run from the backend root:  python -m unittest discover tests
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from match_outcomes import NORMAL, OUTCOME_RULES, WALKOVER, get_rule, resolve_match  # noqa: E402
from standings import compute_team_stats  # noqa: E402


def make_match(id, t1, t2, outcome=NORMAL, winner=None, is_final=False, pool='A'):
    return SimpleNamespace(id=id, team1_id=t1, team2_id=t2, outcome=outcome,
                           winner_team_id=winner, is_final=is_final, pool=pool,
                           outcome_reason=None, outcome_decided_by=None, outcome_decided_at=None)


class NormalOutcomeTests(unittest.TestCase):
    def test_higher_score_wins(self):
        r = resolve_match(make_match(1, 'A', 'B'), 11, 7)
        self.assertTrue(r.counted)
        self.assertEqual(r.winner_team_id, 'A')
        self.assertEqual((r.team1_points, r.team2_points), (11, 7))

    def test_zero_zero_is_not_played_yet(self):
        r = resolve_match(make_match(1, 'A', 'B'), 0, 0)
        self.assertFalse(r.counted)

    def test_tie_counts_without_winner(self):
        r = resolve_match(make_match(1, 'A', 'B'), 8, 8)
        self.assertTrue(r.counted)
        self.assertIsNone(r.winner_team_id)

    def test_unknown_outcome_falls_back_to_normal(self):
        self.assertIs(get_rule('something-new'), OUTCOME_RULES[NORMAL])
        self.assertIs(get_rule(None), OUTCOME_RULES[NORMAL])


class WalkoverOutcomeTests(unittest.TestCase):
    def test_walkover_counts_as_win_with_zero_points(self):
        m = make_match(1, 'A', 'B', outcome=WALKOVER, winner='B', is_final=True)
        r = resolve_match(m, 0, 0)
        self.assertTrue(r.counted)
        self.assertEqual(r.winner_team_id, 'B')
        self.assertEqual((r.team1_points, r.team2_points), (0, 0))

    def test_walkover_ignores_any_recorded_scores(self):
        m = make_match(1, 'A', 'B', outcome=WALKOVER, winner='A', is_final=True)
        r = resolve_match(m, 3, 9)
        self.assertEqual(r.winner_team_id, 'A')
        self.assertEqual((r.team1_points, r.team2_points), (0, 0))

    def test_walkover_not_final_does_not_count(self):
        m = make_match(1, 'A', 'B', outcome=WALKOVER, winner='A', is_final=False)
        self.assertFalse(resolve_match(m, 0, 0).counted)

    def test_walkover_rules(self):
        rule = OUTCOME_RULES[WALKOVER]
        self.assertTrue(rule.is_declarable)
        self.assertFalse(rule.accepts_scores)
        self.assertFalse(OUTCOME_RULES[NORMAL].is_declarable)


class DeclarationValidationTests(unittest.TestCase):
    rule = OUTCOME_RULES[WALKOVER]

    def test_valid(self):
        self.assertIsNone(self.rule.validate_declaration(make_match(1, 'A', 'B'), 'A'))

    def test_winner_must_be_in_match(self):
        self.assertIsNotNone(self.rule.validate_declaration(make_match(1, 'A', 'B'), 'C'))
        self.assertIsNotNone(self.rule.validate_declaration(make_match(1, 'A', 'B'), None))

    def test_cannot_declare_on_final_match(self):
        self.assertEqual(
            self.rule.validate_declaration(make_match(1, 'A', 'B', is_final=True), 'A'),
            'Match is already finalized')

    def test_both_teams_must_be_known(self):
        self.assertIsNotNone(self.rule.validate_declaration(make_match(1, 'A', 'TBD'), 'A'))

    def test_normal_cannot_be_declared(self):
        err = OUTCOME_RULES[NORMAL].validate_declaration(make_match(1, 'A', 'B'), 'A')
        self.assertIsNotNone(err)


class StandingsTests(unittest.TestCase):
    def test_mixed_round(self):
        entries = [
            (make_match(1, 'A', 'B'), 11, 7),                                            # A beats B
            (make_match(2, 'A', 'C'), 0, 0),                                             # not played
            (make_match(3, 'B', 'C', outcome=WALKOVER, winner='B', is_final=True), 0, 0),  # B by walkover
            (make_match(4, 'C', 'A'), 8, 8),                                             # tie
        ]
        stats = compute_team_stats(entries)[None]

        self.assertEqual(stats['A'].matches_won, 1)
        self.assertEqual(len(stats['A'].matches_played), 2)       # match 2 not counted
        self.assertEqual(len(stats['A'].matches_scheduled), 3)
        self.assertEqual(stats['A'].points_difference, 4)

        self.assertEqual(stats['B'].matches_won, 1)               # walkover win counted
        self.assertEqual(len(stats['B'].matches_played), 2)
        self.assertEqual((stats['B'].points_scored, stats['B'].points_lost), (7, 11))  # no walkover points

        self.assertEqual(stats['C'].matches_won, 0)
        self.assertEqual(stats['C'].matches_lost, 2)              # walkover loss + tie

    def test_group_by(self):
        entries = [(make_match(1, 'A', 'B', pool='X'), 11, 2), (make_match(2, 'C', 'D', pool='Y'), 3, 11)]
        groups = compute_team_stats(entries, group_by=lambda m: m.pool)
        self.assertEqual(set(groups), {'X', 'Y'})
        self.assertEqual(groups['Y']['D'].matches_won, 1)


if __name__ == '__main__':
    unittest.main()
