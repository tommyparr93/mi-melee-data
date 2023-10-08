from django.db import transaction
from django.http import HttpResponse
from django.core.paginator import Paginator
from .models import Player, Set, Tournament, TournamentResults, PRSeason, PRSeasonResult
from .forms import TournamentForm, PRForm, PRSeasonForm1, PRSeasonForm, PRSeasonResultFormSet, DuplicatePlayer, ConfirmMergeForm
from .data_entry import enter_tournament, enter_pr_csv, enter_pr_season
from django.views import generic
from django.db.models.functions import Lower
from django.db.models import Q
from django.views.generic.detail import DetailView
from django.shortcuts import render, reverse, redirect
from collections import namedtuple


def players(request):
    return HttpResponse("Hello world!")


# i have duplicate code in h2h, combine at some point
def player_detail_calculations(player, sets):
    wins = sets.filter(winner_id=player.id).count()
    losses = sets.exclude(winner_id=player.id).count()
    wr = (wins / sets.count()) * 100
    num_tournaments = sets.values('tournament_id').distinct().count()
    pr_rank = PRSeasonResult.objects.filter(Q(player_id=player.id) & Q(pr_season_id=1)).first()
    if pr_rank:
        stats = {
            'wins': wins,
            'losses': losses,
            'win_rate': int(wr),
            'set_count': wins + losses,
            'tournament_count': num_tournaments,
            'pr_rank': pr_rank
        }
    else:
        stats = {
            'wins': wins,
            'losses': losses,
            'win_rate': int(wr),
            'set_count': wins + losses,
            'tournament_count': num_tournaments,
        }
    return stats


# need to start accounting for DQs in this model
def get_head_to_head_results(player, sets):
    sets = sets.filter(pr_eligible=True)
    opponents = list(set(list(sets.values_list('player1', flat=True)) + list(sets.values_list('player2', flat=True))))
    opponents.remove(player.id)
    opponents_queryset = Player.objects.filter(id__in=opponents).order_by('name')

    opponent_records = []
    for opponent in opponents_queryset:
        matches = sets.filter(Q(player1=opponent) | Q(player2=opponent))
        wins = 0
        losses = 0
        for match in matches:
            if match.winner_id == player.id:
                wins += 1
            else:
                losses += 1
        wr = (wins / matches.count()) * 100
        opponent_record = {
            'opponent': opponent,
            'wins': wins,
            'losses': losses,
            'win_rate': int(wr),
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
        pr_season_result_formset.form.base_fields['player'].queryset = Player.objects.filter(region_code=7)

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


# need to refactor have logic on this front to pass primary player and "opponent" within the sets context
class PlayerDetailView(DetailView):
    model = Player
    template_name = 'main/player_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        player = self.get_object()
        sets = Set.objects.filter(Q(player1=player) | Q(player2=player)).order_by('-tournament__date')


        # PR Season Filter
        pr_seasons = PRSeason.objects.filter(tournament__in=sets.values('tournament')).distinct()
        context['pr_seasons'] = pr_seasons
        pr_season_id = self.request.GET.get('pr_season')


        if pr_season_id:
            sets = Set.objects.filter(
                Q(player1=player) | Q(player2=player),
                tournament__pr_season_id=pr_season_id
            ).order_by('-tournament__date')
        else:
            sets = Set.objects.filter(
                Q(player1=player) | Q(player2=player)
            ).order_by('-tournament__date')

        if pr_season_id:
            context['pr_season'] = pr_season_id

        # Sets Pagination
        page_number = self.request.GET.get('page')
        paginator = Paginator(sets, 50)
        context['sets'] = paginator.get_page(page_number)


        pr_view = self.request.GET.get('pr_view')
        # Logic to filter and sort player list
        if pr_view:
            h2h_list = get_head_to_head_results(player, sets)
            # Assuming you have a 'pr_notable' field in your Player model
            h2h_list = sorted(h2h_list, key=lambda x: (-x['pr_notable'], (x['opponent'].name or '').lower()),)
            not_priority = [opponent for opponent in h2h_list if not opponent['pr_notable'] and not opponent['losses'] > 0]
            h2h_list = [opponent for opponent in h2h_list if opponent['pr_notable'] or opponent['losses'] > 0]
            h2h_list.extend(not_priority)
            context['pr_view'] = True
        else:
            context['pr_view'] = False
            h2h_list = get_head_to_head_results(player, sets)


        # I'm really confused whats actually happening, it might just be because I'm tired but like the variable names don't match and i'm so confused
        SetDisplay = namedtuple('SetDisplay',
                                ['player1_name', 'player2_name', 'player1_score', 'player2_score', 'tournament_name',
                                 'tournament_date', 'id'])

        for opponent_data in h2h_list:
            opponent = opponent_data['opponent']
            opponent_sets = Set.objects.filter(
                (Q(player1=player) & Q(player2=opponent)) |
                (Q(player2=player) & Q(player1=opponent))
            )
            if pr_season_id:
                opponent_sets = opponent_sets.filter(tournament__pr_season_id=pr_season_id)
            set_display_list = []
            for set in opponent_sets:
                # Determine the ordering of players and their corresponding scores
                if set.player1 == player:
                    p1_name = set.player1.name
                    p2_name = set.player2.name
                    p1_score = set.player1_score
                    p2_score = set.player2_score
                else:
                    p1_name = set.player2.name
                    p2_name = set.player1.name
                    p1_score = set.player2_score
                    p2_score = set.player1_score

                # Create a SetDisplay object with the appropriate data and append it to the list
                set_display = SetDisplay(p1_name, p2_name, p1_score, p2_score, set.tournament.name, set.tournament.date, set.id)
                set_display_list.append(set_display)

            # Assign the list of SetDisplay objects to opponent_data['sets']
            set_display_list.reverse()
            opponent_data['sets'] = set_display_list
        # H2H Queries
        context['h2h'] = h2h_list

        # H2H Pagination

        opponents_page_number = self.request.GET.get('opponents_page')
        opponents_paginator = Paginator(context['h2h'], 40)
        opponents = opponents_paginator.get_page(opponents_page_number)
        context['opponents'] = opponents

        # player detail calculations
        context['calculations'] = player_detail_calculations(player, sets)

        tournaments = Tournament.objects.filter(set__in=sets).distinct()
        if pr_season_id:
            tournaments = Tournament.objects.filter(set__in=sets, pr_season_id=pr_season_id).distinct().order_by(
                '-date')
        else:
            tournaments = Tournament.objects.filter(set__in=sets).distinct().order_by('-date')

        # Optional: Tournament Pagination

        tournaments_page_number = self.request.GET.get('tournaments_page')
        tournaments_paginator = Paginator(tournaments, 40)  # Adjust the number per page as necessary
        paged_tournaments = tournaments_paginator.get_page(tournaments_page_number)
        context['tournaments'] = paged_tournaments

        SetDisplay = namedtuple('SetDisplay',
                                ['player1_name', 'player2_name', 'player1_score', 'player2_score', 'tournament_name',
                                 'tournament_date', 'id', 'p2_id'])

        for tournament in context['tournaments']:
            tournament_sets = Set.objects.filter(
                Q(tournament=tournament),
                Q(player1=player) | Q(player2=player)
            )
            if pr_season_id:
                tournament_sets = tournament_sets.filter(tournament__pr_season_id=pr_season_id)

            set_display_list = []
            for set in tournament_sets:
                # Determine the ordering of players and their corresponding scores
                if set.player1 == player:
                    p1_name = set.player1.name
                    p2_name = set.player2.name
                    p1_score = set.player1_score
                    p2_score = set.player2_score
                    p2_id = set.player2.id
                else:
                    p1_name = set.player2.name
                    p2_name = set.player1.name
                    p1_score = set.player2_score
                    p2_score = set.player1_score
                    p2_id = set.player1.id

                # Create a SetDisplay object with the appropriate data and append it to the list
                set_display = SetDisplay(p1_name, p2_name, p1_score, p2_score, set.tournament.name, set.tournament.date,
                                         set.id, p2_id)
                set_display_list.append(set_display)

            # Attach the sets to the tournament object
            set_display_list.reverse()
            tournament.sets = set_display_list


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

    def get_queryset(self):
        queryset = super().get_queryset()
        # Filter to include only Players where pr_eligible is True
        return queryset.filter(pr_eligible=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pr_season'] = 2  # or whatever value you want to set
        return context
