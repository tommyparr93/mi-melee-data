from django.db import transaction
from django.http import HttpResponse
from django.core.paginator import Paginator
from sqlparse.sql import Case

from .models import Player, Set, Tournament, TournamentResults, PRSeason, PRSeasonResult
from .forms import TournamentForm, PRForm, PRSeasonForm1, PRSeasonForm, PRSeasonResultFormSet, DuplicatePlayer, ConfirmMergeForm
from .data_entry import enter_tournament, enter_pr_csv, enter_pr_season
from django.views import generic
from django.views.generic.detail import DetailView
from django.shortcuts import render, reverse, redirect
from collections import namedtuple, defaultdict
from django.db.models import Count, Q, F, FloatField, Case, When, Value, Prefetch
from django.db.models.functions import Cast, Lower

SetDisplay = namedtuple('SetDisplay', [
    'player1_name', 'player2_name', 'player1_score', 'player2_score',
    'tournament_name', 'tournament_date', 'id', 'p2_id'
])

def players(request):
    return HttpResponse("Hello world!")


# i have duplicate code in h2h, combine at some point
def player_detail_calculations(player, sets):
    # 'sets' is now a Python list, so we use list comprehensions or loops
    set_count = len(sets)

    if set_count == 0:
        return {
            'wins': 0, 'losses': 0, 'win_rate': 0,
            'set_count': 0, 'tournament_count': 0
        }

    # Count wins/losses manually in the list
    wins = sum(1 for s in sets if s.winner_id == player.id)
    losses = set_count - wins
    win_rate = (wins / set_count) * 100

    # Get unique tournament IDs from the list
    num_tournaments = len(set(s.tournament_id for s in sets))

    # Keep your PR rank query as is (since it hits a different model)
    pr_rank = PRSeasonResult.objects.filter(player_id=player.id, pr_season_id=2).first()

    stats = {
        'wins': wins,
        'losses': losses,
        'win_rate': int(win_rate),
        'set_count': set_count,
        'tournament_count': num_tournaments,
        'pr_rank': pr_rank
    }
    return stats


# need to start accounting for DQs in this model
def get_head_to_head_results(player, sets_list):
    # 1. Filter the list for PR eligible sets (in-memory)
    sets_list = [s for s in sets_list if s.pr_eligible]

    # 2. Get unique opponent IDs from the list
    opponent_ids = set()
    for s in sets_list:
        opponent_ids.add(s.player1_id)
        opponent_ids.add(s.player2_id)

    # Remove the player themselves from the opponent set
    opponent_ids.discard(player.id)

    # 3. Fetch the actual Player objects for these IDs
    # This is the ONLY database hit in this function
    opponents_queryset = Player.objects.filter(id__in=opponent_ids).order_by('name')

    opponent_records = []
    for opponent in opponents_queryset:
        # 4. Filter matches for THIS specific opponent from our main list
        matches = [
            s for s in sets_list
            if s.player1_id == opponent.id or s.player2_id == opponent.id
        ]

        match_count = len(matches)
        if match_count == 0:
            continue

        wins = sum(1 for m in matches if m.winner_id == player.id)
        losses = match_count - wins
        wr = (wins / match_count) * 100

        opponent_records.append({
            'opponent': opponent,
            'wins': wins,
            'losses': losses,
            'win_rate': int(wr),
            'count': match_count,
            'pr_notable': opponent.pr_notable
        })

    # Sort by set count descending
    return sorted(opponent_records, key=lambda x: x['count'], reverse=True)

def get_head_to_head_results2(player, sets):
    sets = sets.filter(pr_eligible=True)
    # opponents = list(set(list(sets.values_list('player1', flat=True)) + list(sets.values_list('player2', flat=True))))
    # opponents.remove(player.id)
    opponents = (
        Player.objects.filter(
            Q(id__in=sets.values_list('player1', flat=True)) |
            Q(id__in=sets.values_list('player2', flat=True)),
            pr_eligible=True
        )
        .exclude(id=player.id)
        .order_by('name')
    )

    opponents_queryset = Player.objects.filter(id__in=opponents).order_by('name')
    opponent_records = []
    for opponent in opponents_queryset:
        matches = sets.filter(Q(pr_eligible=True), Q(player1=opponent) | Q(player2=opponent))
        matches = matches.filter(Q(pr_eligible=True), Q(player1=player) | Q(player2=player))
        wins = 0
        losses = 0
        for match in matches:
            if match.winner_id == player.id:
                wins += 1
            else:
                losses += 1

        opponent_record = {
            'opponent': opponent.name,
            'wins': wins,
            'losses': losses,
            'win_rate': 0,
            'count': wins + losses,
            'pr_notable': opponent.pr_notable
        }
        opponent_records.append(opponent_record)

    opponent_records = sorted(opponent_records, key=lambda x: x['count'], reverse=True)

    return opponent_records

def put_tournament(request):

    if request.method == 'POST':
        form = TournamentForm(request.POST)
        if form.is_valid():
            cleaned_data = form.cleaned_data
            tournament_url = cleaned_data['tournament_url']
            is_pr_eligible = cleaned_data['is_pr_eligible']
            print(tournament_url)

            return enter_tournament(tournament_url, is_pr_eligible)


    else:
        context = {'form': TournamentForm()}
        return render(request, 'main/tournament_form.html', context)


def join_duplicate(request):
    player_details = None
    merge_success = False
    if request.method == 'POST':
        form = DuplicatePlayer(request.POST)
        cleaned_data = form
        if 'check_duplicate' in request.POST:
            if form.is_valid():
                cleaned_data = form.cleaned_data
                main_account = cleaned_data['player1']
                duplicate_account = cleaned_data['player2']
                request.session['main_account'] = form.cleaned_data['player1']
                request.session['duplicate_account'] = form.cleaned_data['player2']
                player_details = get_player_details(main_account, duplicate_account)

        elif 'confirm_merge' in request.POST:
            confirm_form = ConfirmMergeForm(request.POST)
            if confirm_form.is_valid() and confirm_form.cleaned_data['confirm_merge']:
                # Assuming you have a function to merge accounts
                main_account = request.session.get('main_account')
                duplicate_account = request.session.get('duplicate_account')
                merge_accounts(main_account, duplicate_account)
                from django.db.models import F, Q
                merge_success = True

    else:
        form = DuplicatePlayer()

    context = {
        'form': form,
        'player_details': player_details,
        'confirm_merge_form': ConfirmMergeForm(),  # Pass the confirmation form to the context
        'merge_success': merge_success,
    }
    return render(request, 'main/join_duplicate.html', context)


def merge_accounts(main_account, duplicate_account):
    with transaction.atomic():
        # Update sets where player1 is player_id_old
        print("UPDATING SETS")
        print(f"Main Account: {main_account}")
        print(f"Duplicate Account: {duplicate_account}")
        Set.objects.filter(player1_id=duplicate_account).update(player1_id=main_account)

        # Update sets where player2 is player_id_old
        Set.objects.filter(player2_id=duplicate_account).update(player2_id=main_account)

        # Update tournament results
        TournamentResults.objects.filter(player_id=duplicate_account).update(player_id=main_account)

        # Delete the old player record
        Player.objects.filter(id=duplicate_account).delete()

        # UpdateWinnerID
        Set.objects.filter(
            ~Q(winner_id=F('player1')) &
            ~Q(winner_id=F('player2')) &
            (Q(player1_score__gt=F('player2_score')) | Q(player2_score__gt=F('player1_score')))
        ).update(
            winner_id=Case(
                When(player1_score__gt=F('player2_score'), then=F('player1')),
                When(player2_score__gt=F('player1_score'), then=F('player2')),
                default=F('winner_id')
            )
        )

        return print("COMPLETED")


def get_player_details(main_account, duplicate_account):
    try:
        # Fetch details of main_account
        main_account_details = Player.objects.get(id=main_account)
        main_account_sets = Set.objects.filter(Q(player1=main_account) | Q(player2=main_account))

        # Fetch details of duplicate_account
        duplicate_account_details = Player.objects.get(id=duplicate_account)
        duplicate_account_sets = Set.objects.filter(Q(player1=duplicate_account) | Q(player2=duplicate_account))

        # Compile details into a dictionary (or you could use a custom class)
        details = {
            'main_account': {
                'id': main_account_details.id,
                'name': main_account_details.name,
                'info': player_detail_calculations(main_account_details, main_account_sets)
            },
            'duplicate_account': {
                'id': duplicate_account_details.id,
                'name': duplicate_account_details.name,
                'info': player_detail_calculations(duplicate_account_details, duplicate_account_sets)
            }
        }

        return details

    except Player.DoesNotExist:
        # Handle case where player does not exist
        print(f"Player with id {main_account} or {duplicate_account} not found!")
        return None


def process_pr_csv(request):
    if request.method == 'POST':
        form = PRForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['csvfile']
            if csv_file.content_type != 'text/csv':
                return render(request, 'main/pr_form.html',
                              {'form': form, 'error': 'Invalid file type. Only CSV files are allowed.'})

        enter_pr_csv(csv_file, form.cleaned_data['pr_season'])

    else:
        form = PRForm()

    return render(request, 'main/pr_form.html', {'form': form})


def create_pr_season(request):
    if request.method == 'POST':
        pr_season_form = PRSeasonForm(request.POST)
        pr_season_result_formset = PRSeasonResultFormSet(request.POST)

        if pr_season_form.is_valid() and pr_season_result_formset.is_valid():
            pr_season = pr_season_form.cleaned_data['pr_season']

            for pr_result in pr_season_result_formset.cleaned_data:
                pr_result_create = PRSeasonResult.objects.create(
                    pr_season_id=pr_season.id,
                    player=pr_result['player'],
                    rank=pr_result['rank']
                ).save()

            # Redirect or do something else
            return redirect(reverse('pr_season_details', kwargs={'pk': pr_season.id}))
    else:
        pr_season_form = PRSeasonForm()
        pr_season_result_formset = PRSeasonResultFormSet(queryset=PRSeasonResult.objects.none())
        pr_season_result_formset.form.base_fields['player'].queryset = Player.objects.filter(region_code=7).order_by(Lower('name'))

    context = {
        'pr_season_form': pr_season_form,
        'pr_season_result_formset': pr_season_result_formset,
    }

    return render(request, 'main/create_pr_season.html', context)


def create_pr_season1(request):
    if request.method == 'POST':
        form = PRSeasonForm1(request.POST)
        if form.is_valid():
            cleaned_date = form.cleaned_data
            season_name = cleaned_date['season_name']
            is_active = cleaned_date['is_active']
            season_start = cleaned_date['season_start']
            season_end = cleaned_date['season_end']

            return enter_pr_season(season_name, season_start, season_end, is_active)

    else:
        form = PRSeasonForm1()

    return render(request, 'main/pr_season_form.html', {'form': form})


class PlayerListView(generic.ListView):
    model = Player
    template_name = 'main/players.html'
    paginate_by = 40
    ordering = [Lower('name')]
    queryset = Player.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.exclude(region_code__isnull=True)
        query = self.request.GET.get('q')
        if query:
            queryset = super().get_queryset()
            queryset = queryset.filter(Q(name__icontains=query))

        return queryset


class TournamentListView(generic.ListView):
    model = Tournament
    template_name = 'main/tournaments.html'
    context_object_name = 'tournaments'
    paginate_by = 25
    ordering = ['-date']
    queryset = Tournament.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Getting distinct PRSeasons related to the displayed tournaments
        all_pr_season_ids = Tournament.objects.values_list('pr_season', flat=True).distinct()
        all_pr_seasons = PRSeason.objects.filter(id__in=all_pr_season_ids).order_by('-end_date')

        # Add pr_seasons to context
        context['pr_seasons'] = all_pr_seasons

        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get('q')
        pr_season_id = self.request.GET.get('pr_season')


        if query:
            queryset = super().get_queryset()
            queryset = queryset.filter(Q(name__icontains=query))

        if pr_season_id:
            queryset = queryset.filter(
                pr_season_id=pr_season_id)  # Assuming pr_season is a foreign key in your Tournament model

        return queryset


# need to refactor have logic on this front to pass primary player and "opponent" within the sets context
class PlayerDetailView(DetailView):
    model = Player
    template_name = 'main/player_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        player = self.get_object()

        # 1. OPTIMIZATION: Fetch all sets with select_related to avoid N+1 queries
        # We fetch the tournament and players in the initial JOIN
        base_sets_qs = Set.objects.filter(
            Q(player1=player) | Q(player2=player)
        ).select_related('tournament', 'player1', 'player2').order_by('-tournament__date')

        # 2. Filtering
        pr_season_id = self.request.GET.get('pr_season')
        if pr_season_id:
            base_sets_qs = base_sets_qs.filter(tournament__pr_season_id=pr_season_id, pr_eligible=True)
            context['pr_season'] = pr_season_id

        # Convert to list to execute once and process in memory
        all_sets = list(base_sets_qs)

        # 3. PR Seasons dropdown (Efficient distinct lookup)
        context['pr_seasons'] = PRSeason.objects.all().order_by('-end_date')

        # 4. Process H2H Logic (In-Memory)
        h2h_data = defaultdict(lambda: {'wins': 0, 'losses': 0, 'opponent_obj': None, 'sets': []})

        for s in all_sets:
            # Determine who the opponent is relative to our main player
            if s.player1_id == player.id:
                opp_obj, opp_id = s.player2, s.player2_id
                p1_score, p2_score = s.player1_score, s.player2_score
            else:
                opp_obj, opp_id = s.player1, s.player1_id
                p1_score, p2_score = s.player2_score, s.player1_score

            if not opp_id: continue

            h2h_data[opp_id]['opponent_obj'] = opp_obj
            if s.winner_id == player.id:
                h2h_data[opp_id]['wins'] += 1
            else:
                h2h_data[opp_id]['losses'] += 1

            # Build display object for the expanded row
            display = SetDisplay(
                player.name, opp_obj.name, p1_score, p2_score,
                s.tournament.name, s.tournament.date, s.id, opp_id
            )
            h2h_data[opp_id]['sets'].append(display)

        # Convert dict to list for pagination/template
        h2h_list = []
        for opp_id, stats in h2h_data.items():
            total = stats['wins'] + stats['losses']
            h2h_list.append({
                'opponent': stats['opponent_obj'],
                'wins': stats['wins'],
                'losses': stats['losses'],
                'win_rate': int((stats['wins'] / total) * 100) if total > 0 else 0,
                'sets': stats['sets'],
                'pr_notable': stats['opponent_obj'].pr_notable if stats['opponent_obj'] else False
            })

        # Sorting logic (Notable players first)
        pr_view = self.request.GET.get('pr_view')
        if pr_view:
            h2h_list = sorted(h2h_list, key=lambda x: (-x['pr_notable'], (x['opponent'].name or '').lower()))
            context['pr_view'] = True
        else:
            h2h_list = sorted(h2h_list, key=lambda x: (x['opponent'].name or '').lower())

        # 5. Tournament List Logic (In-Memory)
        # Group the sets we already fetched by tournament_id
        tourney_sets = defaultdict(list)
        for s in all_sets:
            tourney_sets[s.tournament_id].append(s)

        # Fetch actual tournament objects for the page
        tournament_ids = tourney_sets.keys()
        tournaments = Tournament.objects.filter(id__in=tournament_ids).order_by('-date')

        # Batch fetch placements to avoid N+1 inside the loop
        placements = {res.tournament_id: res.placement for res in
                      TournamentResults.objects.filter(player_id=player.id, tournament_id__in=tournament_ids)}

        for t in tournaments:
            t.placement = placements.get(t.id, "N/A")
            # Calculate records using our pre-fetched sets
            t_sets = tourney_sets[t.id]
            t_wins = sum(1 for s in t_sets if s.winner_id == player.id)
            t.record = {'wins': t_wins, 'losses': len(t_sets) - t_wins}

            # Map sets to display format for template
            t.display_sets = []
            for s in t_sets:
                p2_name = s.player2.name if s.player1_id == player.id else s.player1.name
                p2_id = s.player2_id if s.player1_id == player.id else s.player1_id
                t.display_sets.append({
                    'player1_name': player.name, 'player2_name': p2_name,
                    'p1_score': s.player1_score if s.player1_id == player.id else s.player2_score,
                    'p2_score': s.player2_score if s.player1_id == player.id else s.player1_score,
                    'id': s.id, 'p2_id': p2_id
                })

        # 6. Pagination & Context
        context['opponents'] = Paginator(h2h_list, 40).get_page(self.request.GET.get('opponents_page'))
        context['tournaments'] = Paginator(tournaments, 40).get_page(self.request.GET.get('tournaments_page'))
        context['calculations'] = player_detail_calculations(player, all_sets)

        return context


class PrSeasonDetailView(DetailView):
    model = PRSeason
    template_name = 'main/pr_season_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pr_season = self.get_object()
        context['pr_season'] = pr_season
        pr_members = PRSeasonResult.objects.filter(pr_season_id=pr_season.pk)
        context['pr_members'] = pr_members
        return context


class TournamentDetailView(DetailView):
    model = Tournament
    template_name = 'main/tournament_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tournament = self.get_object()
        sets = Set.objects.filter(tournament_id=tournament.id)
        # Getting distinct players from player1 and player2 fields
        player1_ids = sets.values_list('player1', flat=True).distinct()
        player2_ids = sets.values_list('player2', flat=True).distinct()

        # Combine player1_ids and player2_ids and remove duplicates
        all_player_ids = set(list(player1_ids) + list(player2_ids))

        # Count of distinct players
        distinct_player_count = len(all_player_ids)
        tournament.entrant_count = distinct_player_count
        tournament.save()
        context['count'] = distinct_player_count
        context['sets'] = sets

        results = TournamentResults.objects.filter(tournament_id=tournament).order_by('placement')
        context['results'] = results
        return context


class PrEligiblePlayerListView(PlayerListView):
    template_name = 'main/pr_eligible_players.html'
    context_object_name = 'players'
    paginate_by = 50

    def get_queryset(self):
        active_season = PRSeason.objects.filter(is_active=True).first()
        queryset = Player.objects.filter(pr_eligible=True).select_related('region_code')

        if active_season:

            # 2. PREFETCH: Updated with 'set_set' and 'sets_player2_set'
            season_sets = Set.objects.filter(
                tournament__pr_season=active_season,
                pr_eligible=True  # THIS IS THE CRITICAL LINE
            ).select_related('tournament')
            queryset = queryset.prefetch_related(
                Prefetch('set_set', queryset=season_sets, to_attr='season_sets_p1'),
                Prefetch('sets_player2_set', queryset=season_sets, to_attr='season_sets_p2')
            )

        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(name__icontains=q)

        return queryset.order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        players = list(context['players'])
        active_season = PRSeason.objects.filter(is_active=True).first()

        for player in players:
            # 1. Combine all sets
            p1_sets = getattr(player, 'season_sets_p1', [])
            p2_sets = getattr(player, 'season_sets_p2', [])
            all_season_sets = list(p1_sets) + list(p2_sets)

            # 2. Extract Unique Tournaments directly from the Sets
            # We create a dictionary of { tournament_id: region_code }
            unique_tournies = {}
            for s in all_season_sets:
                if s.tournament_id not in unique_tournies:
                    unique_tournies[s.tournament_id] = s.tournament.region_code_id

            # 3. Calculate Attendance Counts manually
            player.mi_tournies = sum(1 for reg in unique_tournies.values() if reg == 7)
            player.oos_tournies = sum(1 for reg in unique_tournies.values() if reg == 10 or reg is None)
            player.total_tournies = len(unique_tournies)

            # 4. Run your existing win rate function
            player.stats = player_detail_calculations(player, all_season_sets)

        # 5. Sorting (Now using the Python-calculated values)
        ordering = self.request.GET.get('ordering', 'name')
        if ordering == 'wr':
            players.sort(key=lambda x: x.stats.get('win_rate', 0), reverse=True)
        elif ordering == 'mi':
            players.sort(key=lambda x: x.mi_tournies, reverse=True)
        elif ordering == 'oos':
            players.sort(key=lambda x: x.oos_tournies, reverse=True)
        elif ordering == 'total':
            players.sort(key=lambda x: x.total_tournies, reverse=True)
        elif ordering == 'name':
            players.sort(key=lambda x: x.name.lower())

        context['players'] = players
        context['active_season_id'] = active_season.id if active_season else None
        context['active_season_name'] = active_season.name if active_season else "No Active Season"
        return context

def pr_table(request):
    # 1. Get eligible players and the active season
    players = list(Player.objects.filter(pr_eligible=True).order_by(Lower('name')))
    active_pr_season = PRSeason.objects.filter(is_active=True).values_list('id', flat=True).first()

    if not active_pr_season:
        return render(request, 'main/pr-table.html', {'players': [], 'table_data': []})

    # 2. Fetch ALL relevant sets once
    season_sets = Set.objects.filter(
        pr_eligible=True,
        tournament__pr_season_id=active_pr_season,
        player1__pr_eligible=True,
        player2__pr_eligible=True
    ).select_related('player1', 'player2')

    # 3. Build the score map
    h2h_map = defaultdict(lambda: defaultdict(int))
    for s in season_sets:
        winner_id = s.winner_id
        # Manually identify the loser since the model has no loser_id field
        loser_id = s.player2_id if s.player1_id == winner_id else s.player1_id
        h2h_map[winner_id][loser_id] += 1

    # 4. Construct the data grid for the template
    table_data = []
    for p_y in players:
        row = {
            'player_obj': p_y,
            'player_name': p_y.name,
            'opponents': []
        }

        for p_x in players:
            if p_y.id == p_x.id:
                cell = {'wins': 'N/A', 'losses': '', 'is_diag': True}
            else:
                wins = h2h_map[p_y.id][p_x.id]
                losses = h2h_map[p_x.id][p_y.id]
                cell = {
                    'wins': wins,
                    'losses': losses,
                    'is_diag': False,
                    'played': (wins + losses) > 0
                }
            row['opponents'].append(cell)

        table_data.append(row)

    context = {
        'players': players,
        'table_data': table_data,
        'active_pr_season': active_pr_season
    }
    return render(request, 'main/pr-table.html', context)