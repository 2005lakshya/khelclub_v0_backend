"""
Declaring how a match was decided without (fully) playing it, e.g. a walkover.

    GET  /match-outcomes                 -> the outcome types clients can show/offer
    POST /matches/<match_id>/outcome     -> declare an outcome on a match

The endpoint is generic: what is allowed, who wins and which points are recorded
all come from the outcome rules in match_outcomes.py.
"""
from datetime import datetime

from flask import jsonify, request

from match_outcomes import OUTCOME_RULES, describe_outcome
from models import Match, Score, db
from routes.score.score_core import update_successor_match
from socket_instance import socketio
from . import match_bp


@match_bp.route('/match-outcomes', methods=['GET'])
def list_match_outcomes():
    return jsonify({
        'outcomes': [
            {**rule.describe(), 'declarable': rule.is_declarable, 'description': rule.description}
            for rule in OUTCOME_RULES.values()
        ]
    }), 200


def _set_score(match, team_id, points):
    """Create or update the score row for one team (rows are what point reports read)."""
    row = Score.query.filter_by(match_id=match.id, team_id=team_id).first()
    if row is None:
        row = Score(match_id=match.id, team_id=team_id, tournament_id=match.tournament_id)
        db.session.add(row)
    row.score = points
    return row


@match_bp.route('/matches/<int:match_id>/outcome', methods=['POST'])
def declare_match_outcome(match_id):
    data = request.get_json(silent=True) or {}
    outcome_key = data.get('outcome')
    winner_team_id = data.get('winner_team_id')
    tournament_id = data.get('tournament_id')
    reason = (data.get('reason') or '').strip() or None
    decided_by = (data.get('decided_by') or '').strip() or None

    rule = OUTCOME_RULES.get(outcome_key)
    if rule is None:
        return jsonify({
            'error': f"Unknown outcome '{outcome_key}'. Valid outcomes: {', '.join(OUTCOME_RULES)}"
        }), 400

    query = Match.query.filter_by(id=match_id)
    if tournament_id is not None:
        query = query.filter_by(tournament_id=tournament_id)
    match = query.first()
    if match is None:
        return jsonify({'error': 'Match not found'}), 404

    error = rule.validate_declaration(match, winner_team_id)
    if error:
        status = 409 if error == 'Match is already finalized' else 400
        return jsonify({'error': error}), status

    try:
        match.outcome = rule.key
        match.outcome_reason = reason[:255] if reason else None
        match.outcome_decided_by = decided_by[:100] if decided_by else None
        match.outcome_decided_at = datetime.utcnow()
        match.winner_team_id = winner_team_id
        match.is_final = True
        match.status = 'completed'

        # Score rows: if the rule awards fixed points, store them so point totals and
        # reports agree with standings; otherwise keep the scores recorded so far.
        current = {
            team_id: (Score.query.filter_by(match_id=match.id, team_id=team_id).first() or Score(score=0)).score
            for team_id in (match.team1_id, match.team2_id)
        }
        result = rule.resolve(match, current[match.team1_id], current[match.team2_id])
        _set_score(match, match.team1_id, result.team1_points)
        _set_score(match, match.team2_id, result.team2_points)
        db.session.flush()

        # In a knockout, move the winner into the next match (commits the session).
        if match.successor:
            update_successor_match(match.successor, match.id, winner_team_id)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

    payload = {
        'message': f'{rule.label} recorded',
        'match_id': match.id,
        'tournament_id': match.tournament_id,
        'team1_id': match.team1_id,
        'team1_score': result.team1_points,
        'team2_id': match.team2_id,
        'team2_score': result.team2_points,
        'is_final': match.is_final,
        'status': match.status,
        'winner_team_id': match.winner_team_id,
        'outcome': describe_outcome(match),
    }
    # Same event the live score views already listen to.
    socketio.emit('score_update', payload, namespace='/scores')
    return jsonify(payload), 200
