from django.http import HttpResponse
from django.core.paginator import Paginator
from .models import Player, Set, Tournament, TournamentResults
from django.views import generic
from django.db.models import Q
from django.views.generic.detail import DetailView


def players(request):
    return HttpResponse("Hello world!")


# i have duplicate code in h2h, combine at some point
def player_detail_calculations(player, sets):
    wins = sets.filter(winnerid=player.playerid).count()
    losses = sets.exclude(winnerid=player.playerid).count()
    wr = (wins / sets.count()) * 100
    num_tournaments = sets.values('tour').distinct().count()
    stats = {
        'wins': wins,
        'losses': losses,
        'win_rate': int(wr),
        'set_count': wins + losses,
        'tournament_count': num_tournaments
    }
    return stats


# it works but slow, need to speed up
# need to start accounting for DQs in this model
def get_head_to_head_results(player, sets):

    opponents = list(set(list(sets.values_list('player1', flat=True)) + list(sets.values_list('player2', flat=True))))
    opponents.remove(player.playerid)
    opponents_queryset = Player.objects.filter(playerid__in=opponents).order_by('name')

    opponent_records = []

    for opponent in opponents_queryset:
        matches = sets.filter(Q(player1=opponent) | Q(player2=opponent))
        wins = 0
        losses = 0
        for match in matches:
            if match.winnerid == player.playerid:
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


class PlayerListView(generic.ListView):
    model = Player
    template_name = 'main/players.html'
    paginate_by = 25
    ordering = ['name']
    queryset = Player.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get('q')
        if query:
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
        sets = Set.objects.filter(Q(player1=player) | Q(player2=player)).order_by('-tour__date')
        # Sets Pagination
        page_number = self.request.GET.get('page')
        paginator = Paginator(sets, 25)
        context['sets'] = paginator.get_page(page_number)

        # H2H Pagination
        context['h2h'] = get_head_to_head_results(player, sets)
        page_number = self.request.GET.get('page')
        paginator = Paginator(context['h2h'], 25)  # Show 10 opponents per page
        opponents = paginator.get_page(page_number)
        context['opponents'] = opponents

        # below is temporary --- remove when better solution is found to organize tournament info
        context['calculations'] = player_detail_calculations(player, sets)

        return context


class TournamentDetailView(DetailView):
    model = Tournament
    template_name = 'main/tournament_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tournament = self.get_object()
        sets = Set.objects.filter(tour=tournament.tour_id)
        context['sets'] = sets
        results = TournamentResults.objects.filter(tour=tournament.tour_id)
        context['results'] = results
        return context
