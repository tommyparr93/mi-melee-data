"""Read-only data tools shared by every agent backend.

Each tool is a plain function that takes simple arguments and returns a
JSON-serialisable dict. The model picks a tool, we run it here with parameterised
ORM queries, and the compact result goes back to the model. Nothing in this module
writes to the database.

The tools mirror features of the website, so the bot's numbers match its pages.
"""
import json
import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import DatabaseError, connections
from django.db.models import Count, Q
from django.urls import reverse

from main.models import Player, PRSeason, PRSeasonResult, Set, Tournament, TournamentResults

from .sql_guard import ALLOWED_VIEWS, SQLRejected, check_sql, max_rows

logger = logging.getLogger(__name__)

MAX_RESULT_CHARS = 8000
MICHIGAN_REGION = 7              # the site's region code for Michigan events
_NATIONAL = Q(region_code__name='National')       # SSBMRank lists, stored as PR seasons


def _limit(value, default, maximum=None):
    maximum = min(maximum or settings.AGENT_MAX_TOOL_ROWS, settings.AGENT_MAX_TOOL_ROWS)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def _player_ref(player):
    return {'id': player.id, 'name': player.name}


def _iso(value):
    return value.isoformat() if value else None


def _rank_key(rank):
    try:
        return (0, int(rank))
    except (TypeError, ValueError):
        return (1, 0)


def _score(value):
    return 'DQ' if value is not None and value < 0 else value


def _is_dq(s):
    return (s.player1_score or 0) < 0 or (s.player2_score or 0) < 0


def _sets_of(player_id):
    return Set.objects.filter(Q(player1_id=player_id) | Q(player2_id=player_id))


def _opponent_id(s, player_id):
    return s.player2_id if s.player1_id == player_id else s.player1_id


def _season(season_id=None):
    michigan = PRSeason.objects.exclude(_NATIONAL)
    if season_id:
        return michigan.filter(pk=int(season_id)).first()
    return michigan.filter(is_active=True).first()


def _scope(season):
    return 'national' if season.region_code and season.region_code.name == 'National' else 'michigan'


def search_players(query, limit=8):
    query = (query or '').strip()
    if not query:
        return {'error': 'query is required'}
    rows = list(Player.objects.filter(name__icontains=query)
                .select_related('region_code', 'main_char')
                .annotate(set_count=Count('set', distinct=True) + Count('sets_player2_set', distinct=True)))
    # exact tag first, then prefix matches, then the most active players
    lowered = query.lower()
    rows.sort(key=lambda p: ((p.name or '').lower() != lowered,
                             not (p.name or '').lower().startswith(lowered), -p.set_count))
    return {
        'players': [{
            **_player_ref(p),
            'sets': p.set_count,
            'region': p.region_code.name if p.region_code else None,
            'main': p.main_char.name if p.main_char else None,
            'pr_eligible': bool(p.pr_eligible),
        } for p in rows[:_limit(limit, 8, 20)]],
        'total_matches': len(rows),
    }


def _pr_history(player_id, scope='michigan'):
    rows = [r for r in PRSeasonResult.objects.filter(player_id=player_id).select_related('pr_season__region_code')
            if _scope(r.pr_season) == scope]
    rows.sort(key=lambda r: (r.pr_season.start_date or date.min, r.pr_season_id), reverse=True)
    return [{'season_id': r.pr_season_id, 'season': r.pr_season.name, 'rank': r.rank} for r in rows]


def get_player_profile(player_id):
    player = (Player.objects.select_related('region_code', 'main_char', 'secondary_char')
              .filter(pk=player_id).first())
    if not player:
        return {'error': f'no player with id {player_id}'}
    sets = list(_sets_of(player.id).select_related('tournament', 'player1', 'player2')
                .order_by('-tournament__date', '-id'))
    wins = sum(1 for s in sets if s.winner_id == player.id)
    recent = []
    for s in sets[:5]:
        opponent = s.player2 if s.player1_id == player.id else s.player1
        mine, theirs = ((s.player1_score, s.player2_score) if s.player1_id == player.id
                        else (s.player2_score, s.player1_score))
        recent.append({'result': 'W' if s.winner_id == player.id else 'L',
                       'opponent_id': opponent.id if opponent else None,
                       'opponent': opponent.name if opponent else None,
                       'score': f'{_score(mine)}-{_score(theirs)}',
                       'tournament_id': s.tournament_id,
                       'tournament': s.tournament.name if s.tournament else None,
                       'date': _iso(s.tournament.date) if s.tournament else None})
    return {
        'player': _player_ref(player),
        'region': player.region_code.name if player.region_code else None,
        'main': player.main_char.name if player.main_char else None,
        'secondary': player.secondary_char.name if player.secondary_char else None,
        'sets_played': len(sets),
        'set_wins': wins,
        'set_losses': len(sets) - wins,
        'set_win_rate_pct': round(100 * wins / len(sets)) if sets else None,
        'dq_sets_included': sum(1 for s in sets if _is_dq(s)),
        'tournaments_entered': len({s.tournament_id for s in sets if s.tournament_id}),
        'recent_sets': recent,
        'pr_history': _pr_history(player.id),
        'national_rankings': _pr_history(player.id, 'national'),
    }


def get_player_tournaments(player_id, year=None, limit=15):
    results = TournamentResults.objects.filter(player_id=player_id)
    if year:
        results = results.filter(tournament__date__year=int(year))
    rows = (results.order_by('-tournament__date')
            .values('tournament_id', 'tournament__name', 'tournament__date',
                    'tournament__entrant_count', 'placement')[:_limit(limit, 15)])
    return {'results': [{'tournament_id': r['tournament_id'], 'tournament': r['tournament__name'],
                         'date': _iso(r['tournament__date']), 'entrants': r['tournament__entrant_count'],
                         'placement': r['placement']} for r in rows]}


def get_player_journey(player_id, year=None, limit=25):
    """Like the site's journey map: in-person, geocoded events, with the record at each."""
    player = Player.objects.filter(pk=player_id).first()
    if not player:
        return {'error': f'no player with id {player_id}'}
    by_tournament = defaultdict(list)
    for s in _sets_of(player.id).exclude(tournament_id__isnull=True):
        by_tournament[s.tournament_id].append(s)
    tournaments = (Tournament.objects.filter(id__in=by_tournament, lat__isnull=False, lng__isnull=False)
                   .exclude(online=True).order_by('-date'))
    if year:
        tournaments = tournaments.filter(date__year=int(year))
    tournaments = list(tournaments)
    shown = tournaments[:_limit(limit, 25)]
    placements = dict(TournamentResults.objects.filter(player_id=player.id, tournament_id__in=[t.id for t in shown])
                      .values_list('tournament_id', 'placement'))
    notable = dict(Player.objects.filter(Q(pr_notable=True) | Q(pr_eligible=True)).values_list('id', 'name'))
    stops = []
    for t in shown:
        sets = by_tournament[t.id]
        wins = [s for s in sets if s.winner_id == player.id]
        stops.append({'tournament_id': t.id, 'tournament': t.name, 'date': _iso(t.date), 'city': t.city,
                      'state': t.state, 'entrants': t.entrant_count, 'placement': placements.get(t.id),
                      'wins': len(wins), 'losses': len(sets) - len(wins),
                      'notable_wins': [notable[o] for o in (_opponent_id(s, player.id) for s in wins)
                                       if o in notable]})
    return {'player': _player_ref(player), 'total_events': len(tournaments), 'newest_first': stops,
            'states_visited': sorted({t.state for t in tournaments if t.state})}


def get_head_to_head(player_a_id, player_b_id):
    if player_a_id == player_b_id:
        return {'error': 'pick two different players'}
    a = Player.objects.filter(pk=player_a_id).first()
    b = Player.objects.filter(pk=player_b_id).first()
    if not a or not b:
        return {'error': 'one or both player ids do not exist'}
    a_sets = list(_sets_of(a.id).select_related('tournament').order_by('-tournament__date', '-id'))
    b_sets = list(_sets_of(b.id))
    direct = [s for s in a_sets if _opponent_id(s, a.id) == b.id]

    def record(sets):
        return {'player_a_wins': sum(1 for s in sets if s.winner_id == a.id),
                'player_b_wins': sum(1 for s in sets if s.winner_id == b.id), 'sets': len(sets)}

    recent = []
    for s in direct[:8]:
        a_score, b_score = ((s.player1_score, s.player2_score) if s.player1_id == a.id
                            else (s.player2_score, s.player1_score))
        recent.append({'winner': a.name if s.winner_id == a.id else (b.name if s.winner_id == b.id else None),
                       'score': f'{_score(a_score)}-{_score(b_score)}',
                       'tournament_id': s.tournament_id,
                       'tournament': s.tournament.name if s.tournament else None,
                       'date': _iso(s.tournament.date) if s.tournament else None})

    def opponents(sets, player):
        tally = defaultdict(lambda: [0, 0])
        for s in sets:
            opp = _opponent_id(s, player.id)
            if opp and opp not in (a.id, b.id):
                tally[opp][0 if s.winner_id == player.id else 1] += 1
        return tally

    a_vs, b_vs = opponents(a_sets, a), opponents(b_sets, b)
    common_ids = sorted(set(a_vs) & set(b_vs), key=lambda o: -(sum(a_vs[o]) + sum(b_vs[o])))
    names = dict(Player.objects.filter(id__in=common_ids[:10]).values_list('id', 'name'))
    return {
        'player_a': _player_ref(a),
        'player_b': _player_ref(b),
        'all_sets': record(direct),
        'pr_eligible_sets': record([s for s in direct if s.pr_eligible]),
        'recent_sets_newest_first': recent,
        'common_opponents_total': len(common_ids),
        'common_opponents': [{'opponent': names.get(o), 'a_record': f'{a_vs[o][0]}-{a_vs[o][1]}',
                              'b_record': f'{b_vs[o][0]}-{b_vs[o][1]}'} for o in common_ids[:10]],
        'site_page': f"{reverse('analytics')}?tab=h2h&p1={a.id}&p2={b.id}",
    }


def search_tournaments(name=None, year=None, limit=10):
    tournaments = Tournament.objects.all()
    if name:
        tournaments = tournaments.filter(name__icontains=name.strip())
    if year:
        tournaments = tournaments.filter(date__year=int(year))
    total = tournaments.count()
    return {
        'tournaments': [{'id': t.id, 'name': t.name, 'date': _iso(t.date), 'city': t.city, 'state': t.state,
                         'entrants': t.entrant_count, 'online': t.online}
                        for t in tournaments.order_by('-date')[:_limit(limit, 10, 25)]],
        'total_matches': total,
    }


def get_tournament_results(tournament_id, top_n=8):
    tournament = Tournament.objects.filter(pk=tournament_id).first()
    if not tournament:
        return {'error': f'no tournament with id {tournament_id}'}
    rows = (TournamentResults.objects.filter(tournament_id=tournament.id)
            .order_by('placement').values('placement', 'player_id', 'player_id__name')[:_limit(top_n, 8)])
    return {
        'tournament': {'id': tournament.id, 'name': tournament.name, 'date': _iso(tournament.date),
                       'city': tournament.city, 'state': tournament.state, 'entrants': tournament.entrant_count},
        'placements': [{'placement': r['placement'], 'player_id': r['player_id'], 'player': r['player_id__name']}
                       for r in rows],
    }


def list_pr_seasons(scope='michigan'):
    seasons = (PRSeason.objects.select_related('region_code').annotate(ranked=Count('prseasonresult'))
               .order_by('-start_date', '-id'))
    if scope == 'national':
        seasons = seasons.filter(_NATIONAL)
    elif scope != 'all':
        seasons = seasons.exclude(_NATIONAL)
    return {'newest_first': [{'id': s.id, 'name': s.name, 'scope': _scope(s), 'start_date': _iso(s.start_date),
                              'end_date': _iso(s.end_date), 'is_active': s.is_active, 'ranked_players': s.ranked}
                             for s in seasons]}


def get_pr_rankings(season_id, limit=25):
    season = PRSeason.objects.filter(pk=season_id).first()
    if not season:
        return {'error': f'no PR season with id {season_id}'}
    results = [{'rank': r.rank, 'player_id': r.player_id, 'player': r.player.name}
               for r in PRSeasonResult.objects.filter(pr_season=season).select_related('player')]
    results.sort(key=lambda r: _rank_key(r['rank']))
    return {'season': {'id': season.id, 'name': season.name, 'scope': _scope(season)},
            'rankings': results[:_limit(limit, 25)], 'total_ranked': len(results)}


def _season_sets(season):
    return Set.objects.filter(pr_eligible=True, tournament__pr_season=season)


def get_pr_shortlist(season_id=None, sort_by='win_rate', limit=50):
    season = _season(season_id)
    if not season:
        return {'error': 'no such PR season'}
    players = {p.id: p for p in Player.objects.filter(pr_eligible=True)}
    tally = {pid: {'wins': 0, 'sets': 0, 'mi': set(), 'other': set()} for pid in players}
    for s in _season_sets(season).select_related('tournament'):
        for pid in (s.player1_id, s.player2_id):
            if pid not in tally:
                continue
            row = tally[pid]
            row['sets'] += 1
            row['wins'] += s.winner_id == pid
            row['mi' if s.tournament.region_code_id == MICHIGAN_REGION else 'other'].add(s.tournament_id)
    rows = [{'player_id': pid, 'player': players[pid].name, 'sets': t['sets'], 'set_wins': t['wins'],
             'win_rate_pct': round(100 * t['wins'] / t['sets']) if t['sets'] else None,
             'michigan_events': len(t['mi']), 'other_events': len(t['other'])}
            for pid, t in tally.items()]
    keys = {'name': lambda r: (r['player'] or '').lower(),
            'events': lambda r: -(r['michigan_events'] + r['other_events']),
            'win_rate': lambda r: -(r['win_rate_pct'] or 0)}
    rows.sort(key=keys.get(sort_by, keys['win_rate']))
    return {'season': {'id': season.id, 'name': season.name, 'is_active': season.is_active},
            'eligible_players': len(rows), 'players': rows[:_limit(limit, 50)]}


def get_pr_h2h_table(season_id=None, player_id=None):
    season = _season(season_id)
    if not season:
        return {'error': 'no such PR season'}
    eligible = dict(Player.objects.filter(pr_eligible=True).values_list('id', 'name'))
    pairs = defaultdict(lambda: [0, 0])
    for s in _season_sets(season).values('player1_id', 'player2_id', 'winner_id'):
        p1, p2, winner = s['player1_id'], s['player2_id'], s['winner_id']
        if p1 not in eligible or p2 not in eligible or not winner:
            continue
        low, high = min(p1, p2), max(p1, p2)
        pairs[(low, high)][0 if winner == low else 1] += 1
    if player_id:
        player_id = int(player_id)
        if player_id not in eligible:
            return {'error': 'that player is not PR-eligible'}
        rows = []
        for (low, high), wins in pairs.items():
            if player_id in (low, high):
                mine, theirs = wins if player_id == low else wins[::-1]
                other = high if player_id == low else low
                rows.append({'opponent_id': other, 'opponent': eligible[other], 'wins': mine, 'losses': theirs})
        rows.sort(key=lambda r: -(r['wins'] + r['losses']))
        return {'season': {'id': season.id, 'name': season.name},
                'player': {'id': player_id, 'name': eligible[player_id]},
                'total_wins': sum(r['wins'] for r in rows), 'total_losses': sum(r['losses'] for r in rows),
                'matchups': rows[:settings.AGENT_MAX_TOOL_ROWS]}
    ordered = sorted(pairs.items(), key=lambda kv: -sum(kv[1]))
    capped = ordered[:settings.AGENT_MAX_TOOL_ROWS]
    return {
        'season': {'id': season.id, 'name': season.name},
        'matchups_total': len(ordered),
        'truncated': len(capped) < len(ordered),
        'matchups': [{'a_id': a, 'a': eligible[a], 'b_id': b, 'b': eligible[b], 'a_wins': w[0], 'b_wins': w[1]}
                     for (a, b), w in capped],
    }


def get_records(year=None, season_id=None):
    """The site's records page: rivalries, win streaks, most sets and events, biggest events."""
    sets = Set.objects.exclude(winner_id__isnull=True).order_by('tournament__date')
    events = Tournament.objects.filter(region_code=MICHIGAN_REGION).exclude(online=True)
    events = events.exclude(entrant_count__isnull=True)
    if season_id:
        sets, events = sets.filter(tournament__pr_season_id=int(season_id)), events.filter(pr_season_id=int(season_id))
    elif year:
        sets, events = sets.filter(tournament__date__year=int(year)), events.filter(date__year=int(year))

    rivalries = defaultdict(lambda: {'meetings': 0, 'wins': defaultdict(int)})
    total_sets, tournaments = defaultdict(int), defaultdict(set)
    current, best = defaultdict(int), defaultdict(int)
    for s in sets.values('player1_id', 'player2_id', 'winner_id', 'tournament_id'):
        p1, p2, winner, tournament = s['player1_id'], s['player2_id'], s['winner_id'], s['tournament_id']
        if not p1 or not p2:
            continue
        total_sets[p1] += 1
        total_sets[p2] += 1
        if tournament:
            tournaments[p1].add(tournament)
            tournaments[p2].add(tournament)
        key = (min(p1, p2), max(p1, p2))
        rivalries[key]['meetings'] += 1
        rivalries[key]['wins'][winner] += 1
        current[winner] += 1
        current[p2 if winner == p1 else p1] = 0
        best[winner] = max(best[winner], current[winner])

    def top(mapping, score):
        return sorted(mapping, key=lambda k: -score(mapping[k]))[:10]

    top_rivalries = top(rivalries, lambda r: r['meetings'])
    top_streaks, top_sets = top(best, int), top(total_sets, int)
    top_events = top(tournaments, len)
    ids = set(top_streaks) | set(top_sets) | set(top_events) | {p for pair in top_rivalries for p in pair}
    names = dict(Player.objects.filter(id__in=ids).values_list('id', 'name'))
    return {
        'filter': {'year': year, 'season_id': season_id},
        'biggest_rivalries': [{'a_id': a, 'a': names.get(a), 'b_id': b, 'b': names.get(b),
                               'meetings': rivalries[(a, b)]['meetings'],
                               'a_wins': rivalries[(a, b)]['wins'].get(a, 0),
                               'b_wins': rivalries[(a, b)]['wins'].get(b, 0)} for a, b in top_rivalries],
        'longest_win_streaks': [{'player_id': p, 'player': names.get(p), 'streak': best[p]} for p in top_streaks],
        'most_sets': [{'player_id': p, 'player': names.get(p), 'sets': total_sets[p]} for p in top_sets],
        'most_events': [{'player_id': p, 'player': names.get(p), 'events': len(tournaments[p])} for p in top_events],
        'biggest_michigan_events': [{'id': e['id'], 'name': e['name'], 'date': _iso(e['date']),
                                     'entrants': e['entrant_count'], 'city': e['city']}
                                    for e in events.order_by('-entrant_count')
                                    .values('id', 'name', 'date', 'entrant_count', 'city')[:10]],
    }


def get_schema(view=None):
    """Columns and sample rows, read through the agent's own locked-down role."""
    if view is not None and view not in ALLOWED_VIEWS:
        return {'error': f'unknown view; choose one of {", ".join(sorted(ALLOWED_VIEWS))}'}
    out = {}
    with connections['agent'].cursor() as cursor:
        for name in ([view] if view else sorted(ALLOWED_VIEWS)):
            cursor.execute(f'SELECT * FROM agent.{name} LIMIT 3')    # name is from the allowlist
            out[name] = {'columns': [c[0] for c in cursor.description],
                         'sample_rows': [list(r) for r in cursor.fetchall()]}
    return out


def run_sql(query):
    """Run one read-only SELECT against the `agent` views on the agent's own DB role."""
    try:
        safe = check_sql(query)
    except SQLRejected as exc:
        return {'error': str(exc)}
    try:
        with connections['agent'].cursor() as cursor:
            cursor.execute(safe)
            columns = [c[0] for c in cursor.description]
            rows = cursor.fetchall()
    except DatabaseError as exc:
        connections['agent'].close()         # never reuse a connection left in a failed state
        message = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
        return {'error': f'database error: {message}'}
    cap = max_rows()
    return {'columns': columns, 'rows': [list(r) for r in rows[:cap]],
            'row_count': min(len(rows), cap), 'truncated': len(rows) > cap}


def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required)}


_INT = {'type': 'integer'}
_STR = {'type': 'string'}
_PLAYER = _schema({'player_id': _INT}, ['player_id'])

# name -> (callable, description, JSON schema). The order is fixed so the prompt cache stays valid.
_TOOLS = {
    'search_players': (search_players,
        'Find players by tag (partial, case-insensitive), best match first. Returns the ids the other '
        'tools need and each player\'s set count. Tags are not unique.',
        _schema({'query': {**_STR, 'description': 'Tag or part of a tag'}, 'limit': _INT}, ['query'])),
    'get_player_profile': (get_player_profile,
        "One player's region, main and secondary characters, overall set record, events entered, "
        'five most recent sets, Michigan PR history and national rankings. Characters are per player; sets have no character data.',
        _PLAYER),
    'get_player_tournaments': (get_player_tournaments,
        "A player's placements, newest first, optionally for one year.",
        _schema({'player_id': _INT, 'year': _INT, 'limit': _INT}, ['player_id'])),
    'get_player_journey': (get_player_journey,
        'Where a player has travelled: in-person events with city, state, placement, record and '
        'wins over notable players, plus the states visited. Optionally for one year.',
        _schema({'player_id': _INT, 'year': _INT, 'limit': _INT}, ['player_id'])),
    'get_head_to_head': (get_head_to_head,
        'Head-to-head between two players: the record over all sets (what the site\'s H2H page shows) '
        'and over PR-eligible sets only, recent meetings, and common opponents. Say which count you quote.',
        _schema({'player_a_id': _INT, 'player_b_id': _INT}, ['player_a_id', 'player_b_id'])),
    'search_tournaments': (search_tournaments,
        'Find tournaments by name and/or year, newest first. Returns tournament ids.',
        _schema({'name': _STR, 'year': _INT, 'limit': _INT})),
    'get_tournament_results': (get_tournament_results,
        'Details and top placements for one tournament id.',
        _schema({'tournament_id': _INT, 'top_n': _INT}, ['tournament_id'])),
    'list_pr_seasons': (list_pr_seasons,
        'Michigan power-ranking seasons, newest first. A season with ranked_players 0 has no published '
        'rankings yet, so look further back for the latest published ones. Pass scope "national" for '
        'national lists such as SSBMRank, or "all" for both.',
        _schema({'scope': {**_STR, 'enum': ['michigan', 'national', 'all']}})),
    'get_pr_rankings': (get_pr_rankings,
        'The published ranking list for one season id, Michigan or national.',
        _schema({'season_id': _INT, 'limit': _INT}, ['season_id'])),
    'get_pr_shortlist': (get_pr_shortlist,
        'PR-eligible players for a season (default: the active one) with their record in PR-eligible '
        'sets and event attendance, in Michigan and elsewhere. sort_by: win_rate, events or name.',
        _schema({'season_id': _INT, 'sort_by': _STR, 'limit': _INT})),
    'get_pr_h2h_table': (get_pr_h2h_table,
        'Head-to-head records among PR-eligible players in one season (default: the active one). '
        'Pass player_id to get only that player\'s matchups.',
        _schema({'season_id': _INT, 'player_id': _INT})),
    'get_records': (get_records,
        'Top 10 lists: biggest rivalries, longest win streaks, most sets, most events, biggest Michigan '
        'events. All-time, or for one year or PR season.',
        _schema({'year': _INT, 'season_id': _INT})),
}

_SQL_TOOLS = {
    'get_schema': (get_schema,
        'Columns and a few sample rows of the read-only views, to see how values look before querying. '
        'Pass view for just one.',
        _schema({'view': _STR})),
    'run_sql': (run_sql,
        'Run one read-only PostgreSQL SELECT on the views. Use only when no other tool fits, such as '
        'custom aggregates or filters. Rows are capped, so aggregate and sort.',
        _schema({'query': {**_STR, 'description': 'A single SELECT statement'}}, ['query'])),
}

TOOL_FUNCTIONS = {name: spec[0] for name, spec in {**_TOOLS, **_SQL_TOOLS}.items()}


def tool_definitions(sql=False):
    """Backend-neutral tool list: [{'name', 'description', 'parameters'}]."""
    specs = {**_TOOLS, **_SQL_TOOLS} if sql else _TOOLS
    return [{'name': name, 'description': desc, 'parameters': schema}
            for name, (_, desc, schema) in specs.items()]


def run_tool(name, arguments):
    """Run a tool by name for a model. Never raises: errors come back as data so the
    model can recover (e.g. fix a bad id) instead of crashing the chat."""
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return _dumps({'error': f'unknown tool {name!r}', 'available': sorted(TOOL_FUNCTIONS)})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or '{}')
        except json.JSONDecodeError:
            return _dumps({'error': 'arguments were not valid JSON'})
    try:
        result = func(**(arguments or {}))
    except TypeError as exc:
        return _dumps({'error': f'bad arguments for {name}: {exc}'})
    except (ValueError, LookupError) as exc:
        return _dumps({'error': f'{name} failed: {exc}'})
    except Exception:
        logger.exception('Ask Tom tool %s failed', name)
        return _dumps({'error': 'that lookup failed'})
    text = _dumps(result)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '... [truncated; ask for fewer rows or a narrower filter]'
    return text


def _dumps(value):
    return json.dumps(value, default=_json_default, separators=(',', ':'), ensure_ascii=False)


def _json_default(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
