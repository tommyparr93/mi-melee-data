from django.http import HttpResponse
from django.core.paginator import Paginator
from django_filters.views import FilterView
from .filters import PlayerFilter
from .models import Player, Set, Tournament, TournamentResults, PRSeason, PRSeasonResult
from .forms import TournamentForm, PRForm, PRSeasonForm
from .data_entry import enter_tournament, enter_pr_csv, enter_pr_season
from django.views import generic
from django.db.models import Q
from django.views.generic.detail import DetailView
from django.shortcuts import render


def players(request):
    return HttpResponse("Hello world!")


# i have duplicate code in h2h, combine at some point
def player_detail_calculations(player, sets):
    wins = sets.filter(winner_id=player.id).count()
    losses = sets.exclude(winner_id=player.id).count()
    wr = (wins / sets.count()) * 100
    num_tournaments = sets.values('tournament_id').distinct().count()
    stats = {
        'wins': wins,
        'losses': losses,
        'win_rate': int(wr),
        'set_count': wins + losses,
        'tournament_count': num_tournaments
    }
    return stats


# need to start accounting for DQs in this model
def get_head_to_head_results(player, sets):

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
            'count': wins + losses
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
        form = PRSeasonForm(request.POST)
        if form.is_valid():
            cleaned_date = form.cleaned_data
            season_name = cleaned_date['season_name']
            is_active = cleaned_date['is_active']
            season_start = cleaned_date['season_start']
            season_end = cleaned_date['season_end']

            return enter_pr_season(season_name, season_start, season_end, is_active)

    else:
        form = PRSeasonForm()

    return render(request, 'main/pr_season_form.html', {'form': form})


class PlayerListView(generic.ListView):
    model = Player
    template_name = 'main/players.html'
    paginate_by = 25
    ordering = ['name']
    queryset = Player.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get('q')
        region = self.request.GET.get('region')
        if query:
            queryset = queryset.filter(Q(name__icontains=query))
        if region:
            queryset = queryset.filter(Q(region_code__exact='7'))
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

        context['pr_season'] = pr_season_id

        # Sets Pagination
        page_number = self.request.GET.get('page')
        paginator = Paginator(sets, 25)
        context['sets'] = paginator.get_page(page_number)



        # H2H Queries
        context['h2h'] = get_head_to_head_results(player, sets)

        # H2H Pagination
        page_number = self.request.GET.get('page')
        paginator = Paginator(context['h2h'], 25)  # Show 10 opponents per page
        opponents = paginator.get_page(page_number)
        context['opponents'] = opponents

        # player detail calculations
        context['calculations'] = player_detail_calculations(player, sets)

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
        context['sets'] = sets
        results = TournamentResults.objects.filter(tournament_id=tournament).order_by('placement')
        context['results'] = results
        return context
