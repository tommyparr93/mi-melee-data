import csv
import datetime
import io

import environ
import re

from contextlib import contextmanager
import itertools

import psycopg2

from .models import Player, Set, Tournament, TournamentResults, PRSeason, PRSeasonResult
from django.db import models
from django.http import HttpResponseRedirect
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.shortcuts import reverse, redirect
import pysmashgg
from django.db import transaction


def extract_url_values(url):
    pattern = r"/tournament/(?P<tournament_slug>[\w-]+)/event/(?P<event_name>[\w-]+)"
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


def enter_tournament(tournament_url: str, is_pr_eligible: bool = True):

    env = environ.Env()
    environ.Env.read_env()
    smashggToken = env('SMASHGG_TOKEN')
    dbName = env("DB_NAME")
    dbUser = env("DB_USER")
    dbPassword = env("DB_PASSWORD")
    dbHost = env("DB_HOST")
    dbPort = env("DB_PORT")

    smash = pysmashgg.SmashGG(smashggToken, True)

    player_list = Player.objects.all() or []
    player_list = [player.id for player in player_list]

    tournament_list = Tournament.objects.all() or []
    tournament_list = [tournament.id for tournament in tournament_list]

    set_list = Set.objects.all() or []
    set_list = [set.id for set in set_list]

    tournament_info = extract_url_values(tournament_url)
    tournament_slug = tournament_info['tournament_slug']
    event_name = tournament_info['event_name']

    tournament = smash.tournament_show(tournament_slug)
    print(tournament)
    t_name = tournament['name']
    t_date = datetime.datetime.fromtimestamp(tournament['startTimestamp'])
    t_city = tournament['city']
    t_entrants = tournament['entrants']

    events = smash.tournament_show_events(tournament_slug)
    event_id = 0
    for event in events:
        print(event)
        if event['slug'] == event_name:
            event_id = event['id']
            break
    print(f'Event ID: {event_id}')

    if not exists(Tournament, event_id):
        with transaction.atomic():
            print(f'tournament {tournament_slug} not in DB, adding tournament {tournament_slug}')
            print('Getting pr season for tournament')
            pr_season = PRSeason.objects.filter(start_date__lte=t_date, end_date__gte=t_date).first()
            Tournament.objects.create(
                id=event_id,
                name=t_name,
                date=t_date,
                city=t_city,
                entrant_count=t_entrants,
                pr_season=None if not pr_season else pr_season
            ).save()

            i = 1
            get_sets = smash.event_show_sets(event_id, 1)
            sets = []
            while len(get_sets) > 0:
                sets.extend(get_sets)
                i += 1
                get_sets = smash.event_show_sets(event_id, i)

            for melee_set in sets:

                player1 = melee_set['entrant1Players'][0]['playerId']
                player2 = melee_set['entrant2Players'][0]['playerId']
                p1name = (melee_set['entrant1Players'])[0]['playerTag']
                p2name = (melee_set['entrant2Players'])[0]['playerTag']
                # for player in player1, player2:
                #     if not exists(Player, player):
                #
                #             print("HERE HERE HERE ", player)
                #             player_info = smash.player_show_info(player)
                #             # TODO assign region info here as well
                #             Player.objects.create(
                #                 id=player,
                #                 name=player_info['name']
                #             )
                if not exists(Player, player1):
                    Player.objects.create(
                        id=player1,
                        name=p1name
                    )
                if not exists(Player, player2):
                    Player.objects.create(
                        id=player2,
                        name=p2name
                    )

                p1score = melee_set['entrant1Score']
                p2score = melee_set['entrant2Score']

                if p1score > p2score:
                    winner = player1
                    bestOf = 3 if p1score == 2 else 5 if p1score == 3 else None
                else:
                    winner = player2
                    bestOf = 3 if p2score == 2 else 5 if p2score == 3 else None

                playedBool = (p1score + p2score) >= 0

                if melee_set['id'] not in set_list:
                    Set.objects.create(
                        id=melee_set['id'],
                        player1=Player.objects.get(id=player1),
                        player2=Player.objects.get(id=player2),
                        player1_score=p1score,
                        player2_score=p2score,
                        winner_id=winner,
                        tournament_id=event_id,
                        location=melee_set['fullRoundText'],
                        played=playedBool,
                        pr_eligible=is_pr_eligible
                    ).save()
        transaction.commit()
        tournament_results_list = TournamentResults.objects.all() or []
        tournament_results_list = [(tr.tournament, tr.player_id) for tr in tournament_results_list]

        conn = psycopg2.connect(dbname=dbName, user=dbUser, password=dbPassword, host=dbHost, port=dbPort)
        cur = conn.cursor()

        results = smash.tournament_show_lightweight_results(tournament_slug, event_name, 1)
        print(f'results: {results}')
        for result in results:
            player_id = result['playerid']
            placement = result['placement']

            if (event_id, player_id) not in tournament_results_list:
                sql_query = 'INSERT INTO tournament_results (tournament_id, player_id, placement) VALUES (%s, %s, %s)'
                query_parameters = (event_id, player_id, placement)
                cur.execute(sql_query, query_parameters)
                conn.commit()

        conn.close()


        """
        results = smash.tournament_show_lightweight_results(tournament_slug, event_name, 1)
        print(f'results: {results}')
        for result in results:
            player_id = result['playerid']
            placement = result['placement']

            if (event_id, player_id) not in tournament_results_list:
                TournamentResults.objects.create(
                    tournament_id=event_id,
                    player_id=Player.objects.get(id=player_id),
                    placement=placement
                ).save()"""

    return redirect(reverse('tournament_details', kwargs={'pk': event_id}))

