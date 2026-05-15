import csv
import datetime
import io
import time
import environ
import re

from .models import Player, Set, Tournament, TournamentResults, PRSeason, PRSeasonResult
from django.db import models
from django.http import HttpResponseRedirect
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.shortcuts import reverse, redirect
import pysmashgg
from django.db import transaction


def extract_url_values(url):
    # Support both /event/ and /events/ and handle potential doubling or full URLs
    pattern = r"tournament/(?P<tournament_slug>[^/]+)/events?/(?P<event_name>[^/?#]+)"
    matches = re.search(pattern, url)
    if matches:
        return matches.groupdict()
    return {}


def tournament_exists(tournament_id) -> bool:
    print(f'tournament_exists: {tournament_id}')

    tournament = Tournament.objects.filter(pk=tournament_id)
    return True if tournament else False


def set_exists(set_id) -> bool:
    print(f'set_exists: {set_id}')

    melee_set = Set.objects.filter(pk=set_id)
    return True if melee_set else False


def exists(model: models.Model, pk) -> bool:
    print(f'exists: {pk}')

    entries = model.objects.filter(id=pk)
    return True if entries else False


def enter_pr_csv(pr_csv: InMemoryUploadedFile, pr_season: PRSeason):
    decoded_file = pr_csv.read().decode('utf-8')
    io_string = io.StringIO(decoded_file)
    reader = csv.reader(io_string)

    for line in reader:
        PRSeasonResult.objects.create(
            rank=line[0],
            player_id=line[2],
            pr_season_id=pr_season.pk
        ).save()

    return pr_season


def enter_pr_season(name: str, start_date: datetime.datetime, end_date: datetime.datetime, is_active: bool = False):
    PRSeason.objects.create(
        name=name,
        start_date=start_date,
        end_date=end_date,
        is_active=is_active
    ).save()
    return redirect(reverse('pr_season_details', kwargs={'pk': PRSeason.objects.get(name=name).id}))


def enter_tournament(tournament_url: str, is_pr_eligible: bool = True, player_list_cache=None, set_list_cache=None):

    env = environ.Env()
    environ.Env.read_env()
    smashggToken = env('SMASHGG_TOKEN')
    
    smash = pysmashgg.SmashGG(smashggToken, True)

    player_list = player_list_cache if player_list_cache is not None else set(Player.objects.values_list('id', flat=True))
    set_list = set_list_cache if set_list_cache is not None else set(Set.objects.values_list('id', flat=True))

    tournament_info = extract_url_values(tournament_url)
    tournament_slug = tournament_info.get('tournament_slug')
    event_name = tournament_info.get('event_name')

    if not tournament_slug or not event_name:
        raise Exception(f"Invalid URL format: {tournament_url}")

    tournament = smash.tournament_show(tournament_slug)
    if not tournament or 'name' not in tournament:
        raise Exception(f"Tournament '{tournament_slug}' not found or API returned an error.")

    t_name = tournament['name']
    t_date = datetime.datetime.fromtimestamp(tournament['startTimestamp'])
    t_city = tournament['city']
    t_entrants = tournament['entrants'] or 0
    t_state = tournament.get('state')
    t_online = tournament.get('isOnline') or False

    # Assign Region Code: Michigan = 7, Out of State = 10
    region_id = 7 if t_state == 'MI' else 10

    if t_entrants <= 4:
        raise Exception(f"Skipping '{tournament_slug}': Only {t_entrants} entrants.")

    events = smash.tournament_show_events(tournament_slug)
    event_id = 0
    if events:
        for event in events:
            if event['slug'] == event_name:
                event_id = event['id']
                break
                
    if event_id == 0:
        raise Exception(f"Event '{event_name}' not found in tournament '{tournament_slug}'.")

    if exists(Tournament, event_id):
        return redirect(reverse('tournament_details', kwargs={'pk': event_id}))

    print(f'tournament {tournament_slug} not in DB, fetching API data...')

    # Fetch All API Data
    i = 1
    get_sets = smash.event_show_sets(event_id, 1)
    sets = []
    while get_sets and len(get_sets) > 0:
        sets.extend(get_sets)
        i += 1
        time.sleep(1)  # API rate limit
        get_sets = smash.event_show_sets(event_id, i)

    page = 1
    get_results = smash.tournament_show_lightweight_results(tournament_slug, event_name, page)
    all_results = []
    while get_results and len(get_results) > 0:
        all_results.extend(get_results)
        page += 1
        time.sleep(1)  # API rate limit
        get_results = smash.tournament_show_lightweight_results(tournament_slug, event_name, page)

    # Process Data
    sets_to_create = []
    players_to_create = []
    
    for melee_set in sets:
        ent1 = melee_set.get('entrant1Players', [])
        ent2 = melee_set.get('entrant2Players', [])

        # Start.gg sometimes returns [None] for deleted players or deep DQs
        if not ent1 or not ent2 or ent1[0] is None or ent2[0] is None:
            continue

        if not str(melee_set.get('id', '')).isdigit():
            continue

        player1 = ent1[0]['playerId']
        player2 = ent2[0]['playerId']
        p1name = ent1[0]['playerTag']
        p2name = ent2[0]['playerTag']

        if player1 not in player_list:
            players_to_create.append(Player(id=player1, name=p1name))
            player_list.add(player1)
        if player2 not in player_list:
            players_to_create.append(Player(id=player2, name=p2name))
            player_list.add(player2)

        p1score_raw = melee_set.get('entrant1Score')
        p2score_raw = melee_set.get('entrant2Score')

        p1score = p1score_raw if p1score_raw is not None else -1
        p2score = p2score_raw if p2score_raw is not None else -1

        is_set_eligible = is_pr_eligible and (p1score != -1 and p2score != -1)

        if p1score > p2score:
            winner = player1
        else:
            winner = player2

        playedBool = (p1score + p2score) >= 0

        if melee_set['id'] not in set_list:
            sets_to_create.append(Set(
                id=melee_set['id'],
                player1_id=player1,
                player2_id=player2,
                player1_score=p1score,
                player2_score=p2score,
                winner_id=winner,
                tournament_id=event_id,
                location=melee_set['fullRoundText'],
                played=playedBool,
                pr_eligible=is_set_eligible
            ))
            set_list.add(melee_set['id'])

    if not sets_to_create:
        raise Exception(f"Skipping '{tournament_slug}': 0 valid sets found.")

    # Database Transaction
    print(f"Opening database transaction for {tournament_slug}...")
    with transaction.atomic():
        pr_season = PRSeason.objects.filter(start_date__lte=t_date, end_date__gte=t_date).first()
        
        # Create tournament
        Tournament.objects.create(
            id=event_id,
            name=t_name,
            date=t_date,
            city=t_city,
            state=t_state,
            entrant_count=t_entrants,
            pr_season=pr_season,
            slug=tournament_slug,
            region_code_id=region_id,
            online=t_online
        )

        if players_to_create:
            Player.objects.bulk_create(players_to_create, ignore_conflicts=True)
            print(f"Bulk created {len(players_to_create)} players")

        if sets_to_create:
            Set.objects.bulk_create(sets_to_create, ignore_conflicts=True)
            print(f"Bulk created {len(sets_to_create)} sets")

        print(f"Fetched {len(all_results)} total results. Inserting...")
        from django.db import connection
        with connection.cursor() as cur:
            for result in all_results:
                player_id = result['playerid']
                placement = result['placement']
                sql_query = 'INSERT INTO tournament_results (tournament_id, player_id, placement) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING'
                query_parameters = (event_id, player_id, placement)
                cur.execute(sql_query, query_parameters)

    return redirect(reverse('tournament_details', kwargs={'pk': event_id}))


def enter_tournament_async(tournament_url: str, is_pr_eligible: bool = True):
    from django.db import connection
    try:
        enter_tournament(tournament_url, is_pr_eligible=is_pr_eligible)
        print(f"Background ingestion completed successfully for {tournament_url}")
    except Exception as e:
        from .models import SyncErrorLog
        print(f"Background ingestion failed: {e}")
        SyncErrorLog.objects.create(
            tournament_name="Manual Entry",
            tournament_url=tournament_url,
            error_message=f"Async Error: {str(e)}"
        )
    finally:
        connection.close()

