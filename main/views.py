from django.http import HttpResponse
from django.core.paginator import Paginator
from django.shortcuts import render
from .models import Player, Set, Tournament, TournamentResults
from django.views import generic
from django.db.models import Q
from django.views import View
from django.db.models import Value, Case, Sum, IntegerField, When
from django.views.generic.detail import DetailView
from itertools import chain


def players(request):
    return HttpResponse("Hello world!")


# do better lol
def player_detail_calculations(player, sets):
    wins = sets.filter(winnerid=player.playerid).count()
    losses = sets.exclude(winnerid=player.playerid).count()
    wr = (wins/sets.count())*100
    num_tournaments = sets.values('tour').distinct().count()
    return [wins, losses, int(wr), num_tournaments]


# it works but slow, need to speed up
def get_head_to_head_results(player, sets):

    l1 = sets.exclude(player1=player.playerid).values_list('player1_id', flat=True).distinct()
    l2 = sets.exclude(player2=player.playerid).values_list('player2_id', flat=True).distinct()
    opponents = set(l1) | set(l2)
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
            'name': opponent.name,
            'wins': wins,
            'losses': losses,
            'win_rate': int(wr),
        }
        opponent_records.append(opponent_record)
    return opponent_records


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
        context['opponents'] = get_head_to_head_results(player, sets)
        # below is temporary --- remove when better solution is found to organize tournament info
        # tournaments = Tournament.objects.filter(set__in=sets).distinct()
        # context['tournaments'] = tournaments

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



