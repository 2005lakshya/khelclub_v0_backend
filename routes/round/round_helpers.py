from flask import jsonify
from models import Match, Score, Team, db
from standings import compute_team_stats, load_match_entries

def get_cumulative_points_for_round(tournament_id):
    try:
        # Get all matches (with both scores) for the tournament
        entries = load_match_entries(tournament_id)
        if not entries and not Match.query.filter_by(tournament_id=tournament_id).first():
            return jsonify({'error': 'No matches found for this tournament'}), 404

        # Cumulative points and points difference per team, decided by the shared outcome rules
        team_stats = compute_team_stats(entries).get(None, {})

        # Convert to list format for response
        standings = []
        for team_id, stats in team_stats.items():
            team = Team.query.get(team_id)
            if team:
                standings.append({
                    'team_id': team_id,
                    'team_name': team.name,
                    'total_points': stats.points_scored,
                    'points_difference': stats.points_difference
                })

        return jsonify({
            'tournament_id': tournament_id,
            'standings': standings
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500 