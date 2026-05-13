import json
from django.db import transaction, models
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import render, get_object_or_404
from .models import Player, Set, Tournament, TournamentResults, PRSeason, PRSeasonResult
from .forms import TournamentForm, PRSeasonForm, DuplicatePlayer, ConfirmMergeForm, PRSeasonResultForm
from .data_entry import enter_tournament, enter_pr_csv, enter_pr_season
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views import generic
from django.views.generic import ListView, CreateView
from django.views.generic.detail import DetailView
from django.shortcuts import render, reverse, redirect
from collections import namedtuple, defaultdict
from django.urls import reverse_lazy
from django.db.models import Count, Q, F, FloatField, Case, When, Value, Prefetch
from django.db.models.functions import Cast, Lower

class HomeView(generic.TemplateView):
    template_name = 'main/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_players'] = Player.objects.count()
        context['total_tournaments'] = Tournament.objects.count()
        context['total_sets'] = Set.objects.count()
        context['recent_tournaments'] = Tournament.objects.order_by('-date')[:5]
        return context


class GlobalSearchView(generic.TemplateView):
    template_name = 'main/search_results.html'

    def get_template_names(self):
        if self.request.headers.get('HX-Request'):
            return ['main/partials/global_search_dropdown.html']
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get('q')
        if query:
            # Detect if it's a quick search (HTMX) or a full search page
            limit = 5 if self.request.headers.get('HX-Request') else 20
            
            # Prioritize Michigan (region_code=7) players
            context['players'] = Player.objects.filter(name__icontains=query).select_related('region_code').annotate(
                is_michigan=Case(
                    When(region_code_id=7, then=Value(1)),
                    default=Value(0),
                    output_field=models.IntegerField(),
                )
            ).order_by('-is_michigan', Lower('name'))[:limit]
            
            context['tournaments'] = Tournament.objects.filter(name__icontains=query).order_by('-date')[:limit]
            context['query'] = query
        return context


SetDisplay = namedtuple('SetDisplay', [
    'player1_name', 'player2_name', 'player1_score', 'player2_score',
    'tournament_name', 'tournament_date', 'id', 'p2_id'
])


def players(request):
    return HttpResponse("Hello world!")


def player_detail_calculations(player, sets):
    if hasattr(sets, 'aggregate'):
        # It's a QuerySet, use optimized DB aggregation
        stats = sets.aggregate(
            total_sets=Count('id'),
            wins=Count('id', filter=Q(winner_id=player.id)),
            num_tournaments=Count('tournament', distinct=True)
        )
        set_count = stats['total_sets'] or 0
        wins = stats['wins'] or 0
        num_tournaments = stats['num_tournaments'] or 0
        # For recent form, we need a small slice
        recent_sets = list(sets.order_by('-tournament__date')[:5])
    else:
        # It's a list (pre-fetched data), use Python loops
        set_count = len(sets)
        wins = sum(1 for s in sets if s.winner_id == player.id)
        num_tournaments = len(set(s.tournament_id for s in sets))
        recent_sets = sets[:5]

    losses = set_count - wins
    win_rate = int((wins / set_count) * 100) if set_count > 0 else 0

    # Keep your PR rank query (hits a different model)
    pr_rank = PRSeasonResult.objects.filter(player_id=player.id, pr_season_id=2).first()

    recent_form = []
    for s in recent_sets:
        if s.winner_id == player.id:
            recent_form.append('W')
        else:
            recent_form.append('L')

    return {
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'loss_rate': 100 - win_rate,
        'set_count': set_count,
        'tournament_count': num_tournaments,
        'pr_rank': pr_rank,
        'recent_form': recent_form
    }


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


from django.contrib import messages
import threading
from .data_entry import enter_tournament_async

def put_tournament(request):
    if request.method == 'POST':
        form = TournamentForm(request.POST)
        if form.is_valid():
            cleaned_data = form.cleaned_data
            tournament_url = cleaned_data['tournament_url']
            is_pr_eligible = cleaned_data['is_pr_eligible']
            run_in_background = cleaned_data.get('run_in_background', False)
            print(f"Adding tournament: {tournament_url} (Background: {run_in_background})")

            if run_in_background:
                # Spawn a background thread for massive tournaments
                thread = threading.Thread(
                    target=enter_tournament_async, 
                    args=(tournament_url, is_pr_eligible)
                )
                thread.start()
                messages.success(request, "Large tournament download started in the background. Check the Tournaments list or Sync Error Logs in a few minutes.")
                return redirect('tournaments')
            else:
                # Run synchronously for normal tournaments
                try:
                    return enter_tournament(tournament_url, is_pr_eligible)
                except Exception as e:
                    messages.error(request, f"Error: {str(e)}")
                    context = {'form': form}
                    return render(request, 'main/tournament_form.html', context)

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


def add_player_to_season(request, season_id):
    season = get_object_or_404(PRSeason, id=season_id)

    if request.method == 'POST':
        player_name = request.POST.get('player_name')
        rank = request.POST.get('rank')

        # 1. Find the player (handling duplicates by taking the first match)
        player = Player.objects.filter(name__iexact=player_name).first()

        if player and rank:
            # 2. Create the result entry
            PRSeasonResult.objects.create(
                pr_season=season,
                player=player,  # Using 'player' as per the Choice error earlier
                rank=rank
            )
            # 3. Success! Tell HTMX to refresh the dashboard
            return HttpResponse(status=204, headers={'HX-Refresh': 'true'})
        else:
            # If player not found, you could send an error back,
            # but for now, let's just refresh to see the state.
            return HttpResponse(status=204, headers={'HX-Refresh': 'true'})

    # GET logic (Broadened filter for Notable players)
    players = Player.objects.filter(
        Q(pr_eligible=True) | Q(pr_notable=True)
    ).distinct().order_by('name')

    return render(request, 'main/admin/partials/add_player_modal.html', {
        'season': season,
        'all_players': players,
    })


class PlayerListView(generic.ListView):
    model = Player
    template_name = 'main/players.html'
    paginate_by = 40
    ordering = [Lower('name')]
    queryset = Player.objects.all()

    def get_template_names(self):
        if self.request.headers.get('HX-Request'):
            return ['main/partials/player_list_partial.html']
        return [self.template_name]

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

    def get_template_names(self):
        if self.request.headers.get('HX-Request'):
            target = self.request.headers.get('HX-Target')
            if target == 'dashboard-content':
                return ['main/partials/player_dashboard_inner.html']
            
            tab = self.request.GET.get('tab', 'h2h')
            if tab == 'tournaments':
                return ['main/partials/player_tournaments_partial.html']
            return ['main/partials/player_h2h_partial.html']
        return [self.template_name]

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

        # 3. PR Seasons dropdown (Filtered to Michigan - ID 7)
        context['pr_seasons'] = PRSeason.objects.filter(region_code_id=7).order_by('-end_date')

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


class PRSeasonListView(ListView):
    model = PRSeason
    template_name = 'main/pr_season_list.html'
    context_object_name = 'seasons'
    ordering = ['-start_date']

    def get_queryset(self):
        queryset = super().get_queryset()
        region_filter = self.request.GET.get('view', 'mi')  # Default to Michigan

        if region_filter == 'mi':
            # Only Region 7
            return queryset.filter(region_code_id=7)
        else:
            # Everything except Region 7
            return queryset.exclude(region_code_id=7)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass the current view state back to the template
        context['current_view'] = self.request.GET.get('view', 'mi')
        return context


class PRSeasonCreateView(CreateView):
    model = PRSeason
    form_class = PRSeasonForm
    template_name = 'main/pr_season_form.html'
    success_url = reverse_lazy('pr_season_list')

    def form_valid(self, form):
        # First, save the form as usual
        self.object = form.save()

        # Check if the request came from HTMX
        if self.request.headers.get('HX-Request'):
            # Return an empty response with the refresh header
            return HttpResponse(status=204, headers={'HX-Refresh': 'true'})

        # Fallback for non-HTMX requests
        return super().form_valid(form)


class PRSeasonAdminDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = PRSeason
    template_name = 'main/admin/pr_season_dashboard.html' # New template path
    context_object_name = 'season'

    def test_func(self):
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Fetch results with rank, pre-loading player names for speed
        context['ranked_players'] = PRSeasonResult.objects.filter(
            pr_season=self.object
        ).select_related('player').order_by('rank')
        return context


MIN_SETS_FOR_WIN_RATE = 10
TOP_N_PLAYERS = 15
MICHIGAN_REGION_CODE = 7


def _parse_int_param(request, name, default=None):
    raw = request.GET.get(name)
    if raw in (None, '', 'all'):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class AnalyticsView(generic.TemplateView):
    """Shell view — renders the tab nav and loads the General tab by default."""
    template_name = 'main/analytics.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_tab'] = self.request.GET.get('tab', 'general')
        return context


# ---------------------------------------------------------------------------
# Tab 1: General (Fun Stats)
# ---------------------------------------------------------------------------

class AnalyticsGeneralView(generic.TemplateView):
    template_name = 'main/partials/analytics_general.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_year = _parse_int_param(self.request, 'year')

        # --- All sets ordered by tournament date for streak computation ---
        all_sets = list(
            Set.objects.select_related('tournament')
            .exclude(winner_id__isnull=True)
            .order_by('tournament__date')
            .values('player1_id', 'player2_id', 'winner_id')
        )

        # --- Rivalries: group by sorted player pair ---
        rivalry_map = defaultdict(lambda: {'meetings': 0, 'wins': defaultdict(int)})
        total_sets_per_player = defaultdict(int)
        for s in all_sets:
            p1, p2, w = s['player1_id'], s['player2_id'], s['winner_id']
            if not p1 or not p2:
                continue
            total_sets_per_player[p1] += 1
            total_sets_per_player[p2] += 1
            key = (min(p1, p2), max(p1, p2))
            rivalry_map[key]['meetings'] += 1
            rivalry_map[key]['wins'][w] += 1

        # --- Streak computation ---
        current_streak = defaultdict(int)
        best_streak = defaultdict(int)
        for s in all_sets:
            p1, p2, w = s['player1_id'], s['player2_id'], s['winner_id']
            if not p1 or not p2 or not w:
                continue
            loser = p2 if w == p1 else p1
            current_streak[w] += 1
            current_streak[loser] = 0
            if current_streak[w] > best_streak[w]:
                best_streak[w] = current_streak[w]

        # --- Fetch player names for rivalries + streaks ---
        top_rivalry_keys = sorted(rivalry_map.keys(), key=lambda k: rivalry_map[k]['meetings'], reverse=True)[:10]
        streak_player_ids = [pid for pid, _ in sorted(best_streak.items(), key=lambda x: x[1], reverse=True)[:10]]
        player_id_set = set(streak_player_ids)
        for a, b in top_rivalry_keys:
            player_id_set.add(a)
            player_id_set.add(b)
        player_lookup = {p.id: p for p in Player.objects.filter(id__in=player_id_set)}

        # Build rivalry rows
        rivalries = []
        for a_id, b_id in top_rivalry_keys:
            data = rivalry_map[(a_id, b_id)]
            a = player_lookup.get(a_id)
            b = player_lookup.get(b_id)
            if not a or not b:
                continue
            rivalries.append({
                'player_a': a,
                'player_b': b,
                'meetings': data['meetings'],
                'a_wins': data['wins'].get(a_id, 0),
                'b_wins': data['wins'].get(b_id, 0),
            })

        # Build streak leaderboard
        streaks = []
        for pid in streak_player_ids:
            p = player_lookup.get(pid)
            if p:
                streaks.append({'player': p, 'streak': best_streak[pid]})

        # Stat cards
        most_sets_pid = max(total_sets_per_player, key=total_sets_per_player.get) if total_sets_per_player else None
        most_sets_player = Player.objects.filter(id=most_sets_pid).first() if most_sets_pid else None
        biggest_rivalry = rivalries[0] if rivalries else None
        top_streak = streaks[0] if streaks else None

        # --- Top 10 events (filterable by year) ---
        events_qs = Tournament.objects.filter(
            region_code=MICHIGAN_REGION_CODE
        ).exclude(online=True).exclude(entrant_count__isnull=True)
        if selected_year:
            events_qs = events_qs.filter(date__year=selected_year)
        top_events = list(events_qs.order_by('-entrant_count').values('id', 'name', 'date', 'entrant_count', 'city')[:10])

        all_years = list(
            Tournament.objects.filter(region_code=MICHIGAN_REGION_CODE)
            .exclude(date__isnull=True)
            .order_by('date__year')
            .values_list('date__year', flat=True)
            .distinct()
        )

        context.update({
            'rivalries': rivalries,
            'streaks': streaks,
            'top_events': top_events,
            'most_sets_player': most_sets_player,
            'most_sets_count': total_sets_per_player.get(most_sets_pid, 0),
            'biggest_rivalry': biggest_rivalry,
            'top_streak': top_streak,
            'available_years': sorted(set(all_years), reverse=True),
            'selected_year': selected_year,
        })
        return context


# ---------------------------------------------------------------------------
# Tab 2: PR Analytics
# ---------------------------------------------------------------------------

class AnalyticsPRView(generic.TemplateView):
    template_name = 'main/partials/analytics_pr.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_season = _parse_int_param(self.request, 'season')
        top_n = _parse_int_param(self.request, 'top_n', default=TOP_N_PLAYERS) or TOP_N_PLAYERS
        min_sets = _parse_int_param(self.request, 'min_sets', default=MIN_SETS_FOR_WIN_RATE) or MIN_SETS_FOR_WIN_RATE

        sets_qs = Set.objects.all()
        if selected_season is not None:
            sets_qs = sets_qs.filter(tournament__pr_season_id=selected_season)

        wins = defaultdict(int)
        totals = defaultdict(int)
        player_tourneys = defaultdict(set)
        for s in sets_qs.values('player1_id', 'player2_id', 'winner_id', 'tournament_id'):
            p1, p2, w, t = s['player1_id'], s['player2_id'], s['winner_id'], s['tournament_id']
            if p1:
                totals[p1] += 1
                if t:
                    player_tourneys[p1].add(t)
            if p2:
                totals[p2] += 1
                if t:
                    player_tourneys[p2].add(t)
            if w:
                wins[w] += 1

        mi_players = list(Player.objects.filter(region_code=MICHIGAN_REGION_CODE).values('id', 'name'))

        win_rate_rows = []
        activity_rows = []
        player_id_map = {}
        for p in mi_players:
            pid, name = p['id'], p['name'] or 'Unknown'
            player_id_map[pid] = name
            total = totals[pid]
            if total >= min_sets:
                win_rate = round((wins[pid] / total) * 100, 1)
                win_rate_rows.append({'id': pid, 'name': name, 'win_rate': win_rate, 'sets': total})
            tourney_count = len(player_tourneys[pid])
            if tourney_count > 0:
                activity_rows.append({'id': pid, 'name': name, 'tournaments': tourney_count})

        win_rate_rows.sort(key=lambda r: r['win_rate'], reverse=True)
        activity_rows.sort(key=lambda r: r['tournaments'], reverse=True)

        # Tournaments per year
        per_year = defaultdict(int)
        for t in Tournament.objects.filter(region_code=MICHIGAN_REGION_CODE).exclude(online=True).exclude(date__isnull=True).values('date'):
            per_year[t['date'].year] += 1
        per_year_rows = [{'year': str(y), 'count': c} for y, c in sorted(per_year.items())]

        # PR ranking history
        season_results = PRSeasonResult.objects.filter(
            pr_season__region_code=MICHIGAN_REGION_CODE
        ).select_related('player', 'pr_season').order_by('pr_season__start_date', 'rank')

        season_order = []
        season_seen = set()
        player_ranks = defaultdict(dict)
        for r in season_results:
            sname = r.pr_season.name
            if sname not in season_seen:
                season_seen.add(sname)
                season_order.append(sname)
            try:
                rank_val = int(r.rank)
            except (TypeError, ValueError):
                continue
            player_ranks[r.player.name or f'Player {r.player_id}'][sname] = rank_val

        pr_history = [
            {'name': name, 'ranks': [ranks.get(s) for s in season_order]}
            for name, ranks in player_ranks.items()
            if len(ranks) >= 2
        ]
        pr_history.sort(key=lambda p: min(r for r in p['ranks'] if r is not None))

        available_seasons = list(PRSeason.objects.filter(
            region_code=MICHIGAN_REGION_CODE
        ).order_by('-start_date').values('id', 'name'))

        context.update({
            'available_seasons': available_seasons,
            'selected_season': selected_season,
            'selected_top_n': top_n,
            'selected_min_sets': min_sets,
            'top_n_options': [10, 15, 20, 30],
            'min_sets_options': [5, 10, 20, 50],
            'win_rate_data': json.dumps(win_rate_rows[:top_n], cls=DjangoJSONEncoder),
            'activity_data': json.dumps(activity_rows[:top_n], cls=DjangoJSONEncoder),
            'tournaments_per_year_data': json.dumps(per_year_rows, cls=DjangoJSONEncoder),
            'pr_history_data': json.dumps({'seasons': season_order, 'players': pr_history}, cls=DjangoJSONEncoder),
        })
        return context


# ---------------------------------------------------------------------------
# Tab 3: Head to Head
# ---------------------------------------------------------------------------

class AnalyticsH2HView(generic.TemplateView):
    template_name = 'main/partials/analytics_h2h.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        p1_id = _parse_int_param(self.request, 'p1')
        p2_id = _parse_int_param(self.request, 'p2')

        if not p1_id or not p2_id or p1_id == p2_id:
            return context

        try:
            p1 = Player.objects.get(id=p1_id)
            p2 = Player.objects.get(id=p2_id)
        except Player.DoesNotExist:
            return context

        # All sets involving either player
        all_sets = list(
            Set.objects.filter(
                Q(player1_id__in=[p1_id, p2_id]) | Q(player2_id__in=[p1_id, p2_id])
            ).select_related('tournament').order_by('tournament__date')
        )

        # Direct H2H record
        direct_sets = [s for s in all_sets if
                       (s.player1_id == p1_id or s.player2_id == p1_id) and
                       (s.player1_id == p2_id or s.player2_id == p2_id)]
        p1_direct_wins = sum(1 for s in direct_sets if s.winner_id == p1_id)
        p2_direct_wins = sum(1 for s in direct_sets if s.winner_id == p2_id)

        # Side-by-side stats
        def player_stats(player, sets):
            player_sets = [s for s in sets if s.player1_id == player.id or s.player2_id == player.id]
            total = len(player_sets)
            w = sum(1 for s in player_sets if s.winner_id == player.id)
            tourneys = len({s.tournament_id for s in player_sets if s.tournament_id})
            wr = round((w / total) * 100, 1) if total > 0 else 0
            pr = PRSeasonResult.objects.filter(player=player).order_by('rank').first()
            best_pr = PRSeasonResult.objects.filter(player=player).order_by('rank').values_list('rank', flat=True)
            best_rank = min((int(r) for r in best_pr if r and r.isdigit()), default=None)
            return {'wins': w, 'losses': total - w, 'win_rate': wr, 'total': total,
                    'tournaments': tourneys, 'current_pr': pr, 'best_rank': best_rank}

        # Use full set history (not just shared sets) for side-by-side
        p1_all = list(Set.objects.filter(
            Q(player1_id=p1_id) | Q(player2_id=p1_id)
        ).select_related('tournament'))
        p2_all = list(Set.objects.filter(
            Q(player1_id=p2_id) | Q(player2_id=p2_id)
        ).select_related('tournament'))

        p1_stats = player_stats(p1, p1_all)
        p2_stats = player_stats(p2, p2_all)

        # Common opponents
        p1_opponents = defaultdict(lambda: {'w': 0, 'l': 0})
        p2_opponents = defaultdict(lambda: {'w': 0, 'l': 0})
        for s in p1_all:
            opp = s.player2_id if s.player1_id == p1_id else s.player1_id
            if not opp or opp == p2_id:
                continue
            if s.winner_id == p1_id:
                p1_opponents[opp]['w'] += 1
            else:
                p1_opponents[opp]['l'] += 1
        for s in p2_all:
            opp = s.player2_id if s.player1_id == p2_id else s.player1_id
            if not opp or opp == p1_id:
                continue
            if s.winner_id == p2_id:
                p2_opponents[opp]['w'] += 1
            else:
                p2_opponents[opp]['l'] += 1

        common_opp_ids = set(p1_opponents.keys()) & set(p2_opponents.keys())
        common_opp_players = {p.id: p for p in Player.objects.filter(id__in=common_opp_ids)}
        common_opponents = []
        for opp_id in common_opp_ids:
            opp = common_opp_players.get(opp_id)
            if not opp:
                continue
            p1r = p1_opponents[opp_id]
            p2r = p2_opponents[opp_id]
            p1_wr = round(p1r['w'] / (p1r['w'] + p1r['l']) * 100) if (p1r['w'] + p1r['l']) > 0 else 0
            p2_wr = round(p2r['w'] / (p2r['w'] + p2r['l']) * 100) if (p2r['w'] + p2r['l']) > 0 else 0
            total = p1r['w'] + p1r['l'] + p2r['w'] + p2r['l']
            common_opponents.append({
                'opponent': opp,
                'p1_w': p1r['w'], 'p1_l': p1r['l'], 'p1_wr': p1_wr,
                'p2_w': p2r['w'], 'p2_l': p2r['l'], 'p2_wr': p2_wr,
                'total': total,
                'advantage': p1.name if p1_wr > p2_wr else (p2.name if p2_wr > p1_wr else 'Even'),
            })
        common_opponents.sort(key=lambda x: x['total'], reverse=True)

        # Win rate by year
        def win_rate_by_year(player, sets):
            by_year = defaultdict(lambda: {'w': 0, 't': 0})
            for s in sets:
                yr = s.tournament.date.year if s.tournament and s.tournament.date else None
                if not yr:
                    continue
                by_year[yr]['t'] += 1
                if s.winner_id == player.id:
                    by_year[yr]['w'] += 1
            return {str(y): round(d['w'] / d['t'] * 100, 1) if d['t'] > 0 else 0
                    for y, d in sorted(by_year.items())}

        p1_yearly = win_rate_by_year(p1, p1_all)
        p2_yearly = win_rate_by_year(p2, p2_all)
        all_years = sorted(set(p1_yearly.keys()) | set(p2_yearly.keys()))
        yearly_chart = {
            'years': all_years,
            'p1': [p1_yearly.get(y) for y in all_years],
            'p2': [p2_yearly.get(y) for y in all_years],
        }

        context.update({
            'p1': p1, 'p2': p2,
            'p1_direct_wins': p1_direct_wins,
            'p2_direct_wins': p2_direct_wins,
            'direct_total': len(direct_sets),
            'p1_stats': p1_stats,
            'p2_stats': p2_stats,
            'common_opponents': common_opponents[:15],
            'yearly_chart_data': json.dumps(yearly_chart, cls=DjangoJSONEncoder),
        })
        return context


class AnalyticsPlayerSearchView(generic.TemplateView):
    """Lightweight player search for the H2H picker."""
    template_name = 'main/partials/analytics_player_search.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get('q', '').strip()
        num = self.request.GET.get('num', '1')
        players = (Player.objects.filter(name__icontains=q).select_related('region_code').order_by('name')[:8]
                   if len(q) >= 2 else [])
        context.update({'players': players, 'num': num})
        return context