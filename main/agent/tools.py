"""Read-only data tools shared by every agent backend.

Each tool is a plain function that takes simple arguments and returns a
JSON-serialisable dict. Agents never touch the ORM directly: the model picks a
tool, we run it here, and the result goes back to the model. Nothing in this
module writes to the database.
"""
import json
from datetime import date

from django.db.models import Count, Q

from main.models import (
    Player, PRSeason, PRSeasonResult, Set, Tournament, TournamentResults,
)

MAX_RESULT_CHARS = 6000
MAX_LIMIT = 50


def _limit(value, default, maximum=MAX_LIMIT):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, maximum))


def _player_ref(player):
    return {'id': player.id, 'name': player.name}


def _rank_key(result):
    try:
        return (0, int(result['rank']))
    except (TypeError, ValueError):
        return (1, 0)


def _player_sets(player_id, pr_eligible_only=False):
    sets = Set.objects.filter(Q(player1_id=player_id) | Q(player2_id=player_id))
    if pr_eligible_only:
        sets = sets.filter(pr_eligible=True)
    return sets


def find_player(name, limit=8):
    """Look up players by (partial) tag. Always call this first to get a player id."""
    name = (name or '').strip()
    if not name:
        return {'error': 'name is required'}
    limit = _limit(limit, 8, 20)
    matches = (Player.objects.filter(name__icontains=name)
               .select_related('region_code', 'main_char')
               .annotate(set_count=Count('set', distinct=True) + Count('sets_player2_set', distinct=True)))
    rows = list(matches)
    # exact tag first, then prefix matches, then the most active players
    rows.sort(key=lambda p: (
        (p.name or '').lower() != name.lower(),
        not (p.name or '').lower().startswith(name.lower()),
        -p.set_count,
    ))
    return {
        'players': [{
            'id': p.id,
            'name': p.name,
            'region': p.region_code.name if p.region_code else None,
            'main_character': p.main_char.name if p.main_char else None,
            'pr_eligible': bool(p.pr_eligible),
        } for p in rows[:limit]],
        'total_matches': len(rows),
    }


def get_player_summary(player_id):
    """Overall record, tournament count, recent form and PR history for one player."""
    player = Player.objects.select_related('region_code', 'main_char', 'secondary_char').filter(pk=player_id).first()
    if not player:
        return {'error': f'no player with id {player_id}'}
    sets = _player_sets(player.id)
    totals = sets.aggregate(
        total_sets=Count('id'),
        wins=Count('id', filter=Q(winner_id=player.id)),
        tournaments=Count('tournament', distinct=True),
    )
    total, wins = totals['total_sets'] or 0, totals['wins'] or 0
    recent = list(sets.select_related('tournament', 'player1', 'player2').order_by('-tournament__date', '-id')[:5])
    recent_form = []
    for s in recent:
        opponent = s.player2 if s.player1_id == player.id else s.player1
        recent_form.append({
            'result': 'W' if s.winner_id == player.id else 'L',
            'opponent': opponent.name if opponent else None,
            'score': f'{s.player1_score}-{s.player2_score}',
            'tournament': s.tournament.name if s.tournament else None,
            'date': s.tournament.date.isoformat() if s.tournament and s.tournament.date else None,
        })
    return {
        'player': _player_ref(player),
        'region': player.region_code.name if player.region_code else None,
        'main_character': player.main_char.name if player.main_char else None,
        'secondary_character': player.secondary_char.name if player.secondary_char else None,
        'sets_played': total,
        'set_wins': wins,
        'set_losses': total - wins,
        'set_win_rate_pct': round(100 * wins / total) if total else None,
        'tournaments_entered': totals['tournaments'] or 0,
        'recent_sets': recent_form,
        'pr_history': get_player_pr_history(player.id)['seasons'],
    }


def get_player_pr_history(player_id):
    """The player's rank in each PR season they appeared on."""
    results = (PRSeasonResult.objects.filter(player_id=player_id)
               .select_related('pr_season').order_by('-pr_season__start_date', '-pr_season_id'))
    return {'seasons': [{
        'season_id': r.pr_season_id,
        'season': r.pr_season.name,
        'rank': r.rank,
    } for r in results]}


def get_head_to_head(player_a_id, player_b_id, pr_eligible_only=True):
    """Set record between two players plus their most recent meetings."""
    if player_a_id == player_b_id:
        return {'error': 'pick two different players'}
    a = Player.objects.filter(pk=player_a_id).first()
    b = Player.objects.filter(pk=player_b_id).first()
    if not a or not b:
        return {'error': 'one or both player ids do not exist'}
    sets = Set.objects.filter(
        Q(player1_id=a.id, player2_id=b.id) | Q(player1_id=b.id, player2_id=a.id))
    if pr_eligible_only:
        sets = sets.filter(pr_eligible=True)
    sets = sets.select_related('tournament').order_by('-tournament__date', '-id')
    rows = list(sets)
    a_wins = sum(1 for s in rows if s.winner_id == a.id)
    b_wins = sum(1 for s in rows if s.winner_id == b.id)
    recent = []
    for s in rows[:10]:
        a_score = s.player1_score if s.player1_id == a.id else s.player2_score
        b_score = s.player2_score if s.player1_id == a.id else s.player1_score
        recent.append({
            'winner': a.name if s.winner_id == a.id else (b.name if s.winner_id == b.id else None),
            'score': f'{a.name} {a_score} - {b_score} {b.name}',
            'tournament': s.tournament.name if s.tournament else None,
            'date': s.tournament.date.isoformat() if s.tournament and s.tournament.date else None,
        })
    return {
        'player_a': _player_ref(a),
        'player_b': _player_ref(b),
        'total_sets': len(rows),
        'player_a_wins': a_wins,
        'player_b_wins': b_wins,
        'pr_eligible_sets_only': bool(pr_eligible_only),
        'recent_sets': recent,
    }


def get_player_tournament_results(player_id, year=None, limit=15):
    """Tournaments a player entered with their placement, newest first."""
    limit = _limit(limit, 15)
    results = TournamentResults.objects.filter(player_id=player_id)
    if year:
        results = results.filter(tournament__date__year=int(year))
    rows = (results.order_by('-tournament__date')
            .values('tournament_id', 'tournament__name', 'tournament__date',
                    'tournament__entrant_count', 'placement')[:limit])
    return {'results': [{
        'tournament_id': r['tournament_id'],
        'tournament': r['tournament__name'],
        'date': r['tournament__date'].isoformat() if r['tournament__date'] else None,
        'entrants': r['tournament__entrant_count'],
        'placement': r['placement'],
    } for r in rows]}


def find_tournament(name=None, year=None, limit=10):
    """Search tournaments by name and/or year; returns ids for get_tournament_results."""
    limit = _limit(limit, 10, 25)
    tournaments = Tournament.objects.all()
    if name:
        tournaments = tournaments.filter(name__icontains=name.strip())
    if year:
        tournaments = tournaments.filter(date__year=int(year))
    total = tournaments.count()
    rows = tournaments.select_related('region_code').order_by('-date')[:limit]
    return {
        'tournaments': [{
            'id': t.id,
            'name': t.name,
            'date': t.date.isoformat() if t.date else None,
            'city': t.city,
            'state': t.state,
            'entrants': t.entrant_count,
            'online': t.online,
        } for t in rows],
        'total_matches': total,
    }


def get_tournament_results(tournament_id, top_n=8):
    """Top placements for one tournament."""
    top_n = _limit(top_n, 8)
    tournament = Tournament.objects.filter(pk=tournament_id).first()
    if not tournament:
        return {'error': f'no tournament with id {tournament_id}'}
    rows = (TournamentResults.objects.filter(tournament_id=tournament.id)
            .order_by('placement').values('placement', 'player_id', 'player_id__name')[:top_n])
    return {
        'tournament': {
            'id': tournament.id,
            'name': tournament.name,
            'date': tournament.date.isoformat() if tournament.date else None,
            'city': tournament.city,
            'entrants': tournament.entrant_count,
        },
        'placements': [{
            'placement': r['placement'],
            'player_id': r['player_id'],
            'player': r['player_id__name'],
        } for r in rows],
    }


def list_pr_seasons():
    """All power-ranking seasons with ids and their top three, newest first."""
    seasons = PRSeason.objects.annotate(ranked=Count('prseasonresult')).order_by('-start_date', '-id')
    top = {}
    for r in PRSeasonResult.objects.select_related('player'):
        top.setdefault(r.pr_season_id, []).append({'rank': r.rank, 'player': r.player.name})
    out = []
    for s in seasons:
        podium = sorted(top.get(s.id, []), key=_rank_key)[:3]
        out.append({
            'id': s.id,
            'name': s.name,
            'start_date': s.start_date.isoformat() if s.start_date else None,
            'end_date': s.end_date.isoformat() if s.end_date else None,
            'is_active': s.is_active,
            'ranked_players': s.ranked,
            'top_three': podium,
        })
    return {'seasons': out}


def get_pr_rankings(season_id, limit=25):
    """The ranked player list for one PR season."""
    limit = _limit(limit, 25)
    season = PRSeason.objects.filter(pk=season_id).first()
    if not season:
        return {'error': f'no PR season with id {season_id}; call list_pr_seasons'}
    results = [{'rank': r.rank, 'player_id': r.player_id, 'player': r.player.name}
               for r in PRSeasonResult.objects.filter(pr_season=season).select_related('player')]
    results.sort(key=_rank_key)
    return {
        'season': {'id': season.id, 'name': season.name},
        'rankings': results[:limit],
        'total_ranked': len(results),
    }


def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required)}


_INT = {'type': 'integer'}

# name -> (callable, description, JSON schema). Order is the order the model sees.
_TOOLS = {
    'find_player': (find_player,
        'Search players by tag (case-insensitive, partial match). Call this first whenever the '
        'user mentions a player, to get the numeric player id the other tools need.',
        _schema({'name': {'type': 'string', 'description': 'Player tag or part of it'},
                 'limit': {**_INT, 'description': 'Max matches (default 8)'}}, ['name'])),
    'get_player_summary': (get_player_summary,
        'Overall set record, tournaments entered, recent sets, main character and PR history '
        'for one player.',
        _schema({'player_id': _INT}, ['player_id'])),
    'get_player_pr_history': (get_player_pr_history,
        "A player's rank in each power-ranking season they were on.",
        _schema({'player_id': _INT}, ['player_id'])),
    'get_head_to_head': (get_head_to_head,
        'Set record and recent meetings between two players.',
        _schema({'player_a_id': _INT, 'player_b_id': _INT,
                 'pr_eligible_only': {'type': 'boolean',
                                      'description': 'Only count PR-eligible sets (default true, matches the website)'}},
                ['player_a_id', 'player_b_id'])),
    'get_player_tournament_results': (get_player_tournament_results,
        "A player's tournament placements, newest first. Optionally filter by year.",
        _schema({'player_id': _INT, 'year': _INT, 'limit': {**_INT, 'description': 'Default 15'}}, ['player_id'])),
    'find_tournament': (find_tournament,
        'Search tournaments by name and/or year. Returns tournament ids.',
        _schema({'name': {'type': 'string'}, 'year': _INT, 'limit': {**_INT, 'description': 'Default 10'}})),
    'get_tournament_results': (get_tournament_results,
        'Top placements and basic info for one tournament id.',
        _schema({'tournament_id': _INT, 'top_n': {**_INT, 'description': 'Default 8'}}, ['tournament_id'])),
    'list_pr_seasons': (list_pr_seasons,
        'All power-ranking (PR) seasons with ids, dates, how many players are ranked and the top three. A season with 0 ranked players has no published rankings yet.',
        _schema({})),
    'get_pr_rankings': (get_pr_rankings,
        'The ranked player list for one PR season id (use list_pr_seasons to find it).',
        _schema({'season_id': _INT, 'limit': {**_INT, 'description': 'Default 25'}}, ['season_id'])),
}

TOOL_FUNCTIONS = {name: spec[0] for name, spec in _TOOLS.items()}


def tool_definitions():
    """Backend-neutral tool list: [{'name', 'description', 'parameters'}]."""
    return [{'name': name, 'description': desc, 'parameters': schema}
            for name, (_, desc, schema) in _TOOLS.items()]


def run_tool(name, arguments):
    """Run a tool by name for a model. Never raises: errors come back as data so the
    model can recover (e.g. fix a bad id) instead of crashing the chat."""
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return json.dumps({'error': f'unknown tool {name!r}', 'available': sorted(TOOL_FUNCTIONS)})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or '{}')
        except json.JSONDecodeError:
            return json.dumps({'error': 'arguments were not valid JSON'})
    try:
        result = func(**(arguments or {}))
    except TypeError as exc:
        return json.dumps({'error': f'bad arguments for {name}: {exc}'})
    except (ValueError, LookupError) as exc:
        return json.dumps({'error': f'{name} failed: {exc}'})
    text = json.dumps(result, default=_json_default)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '... [truncated; ask for fewer rows or a narrower filter]'
    return text


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
