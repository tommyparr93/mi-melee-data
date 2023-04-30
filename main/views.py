from django.http import HttpResponse
from django.core.paginator import Paginator
from django.shortcuts import render
from .models import Player, Set, Tournament, TournamentResults
from django.views import generic
from django.db.models import Q
from django.views import View
from django.db.models import Value, Case, Sum, IntegerField, When
from django.views.generic.detail import DetailView


def players(request):
    return HttpResponse("Hello world!")


# do better lol
def player_detail_calculations(player, sets):
    wins = sets.filter(winnerid=player.playerid).count()
    losses = sets.exclude(winnerid=player.playerid).count()
    wr = (wins/sets.count())*100
    return [wins, losses, int(wr)]


class PlayerListView(generic.ListView):
    model = Player
    template_name = 'main/players.html'
    context_object_name = 'users'
    paginate_by = 25
    ordering = ['name']
    queryset = Player.objects.all()


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
        sets = Set.objects.filter(Q(player1=player) | Q(player2=player))
        context['sets'] = sets
        # below is temporary --- remove when better solution is found to organize tournament info
        tournaments = Tournament.objects.filter(set__in=sets).distinct()
        context['tournaments'] = tournaments
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



