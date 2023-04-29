from django.http import HttpResponse
from django.core.paginator import Paginator
from django.shortcuts import render
from .models import Player
from django.views import generic


def players(request):
    return HttpResponse("Hello world!")


class PlayerListView(generic.ListView):
    model = Player
    template_name = 'players/index.html'  # Default: <app_label>/<model_name>_list.html
    context_object_name = 'users'  # Default: object_list
    paginate_by = 25
    ordering = ['name']
    queryset = Player.objects.all()  # Default: Model.objects.all()
