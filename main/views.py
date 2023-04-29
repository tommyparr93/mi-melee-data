from django.http import HttpResponse
from django.core.paginator import Paginator
from django.shortcuts import render
from .models import Player, Set
from django.views import generic
from django.db.models import Q
from django.views import View
from django.db.models import Value, Case, Sum, IntegerField, When
from django.views.generic.detail import DetailView


def players(request):
    return HttpResponse("Hello world!")


class PlayerListView(generic.ListView):
    model = Player
    template_name = 'main/index.html'  # Default: <app_label>/<model_name>_list.html
    context_object_name = 'users'  # Default: object_list
    paginate_by = 25
    ordering = ['name']
    queryset = Player.objects.all()  # Default: Model.objects.all()


class PlayerDetailView(DetailView):
    model = Player
    template_name = 'main/player_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        player = self.get_object()
        sets = Set.objects.filter(Q(player1=player) | Q(player2=player))
        context['sets'] = sets
        return context


class PlayerDetailView2(generic.ListView):
    model = Player
    template_name = 'main/index.html'  # Default: <app_label>/<model_name>_list.html
    context_object_name = 'users'  # Default: object_list
    paginate_by = 25
    ordering = ['name']
    queryset = Player.objects.all()  # Default: Model.objects.all()


