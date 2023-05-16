from django_filters import CharFilter, FilterSet, ChoiceFilter
from .models import Player

class PlayerFilter(FilterSet):
    region = ChoiceFilter(choices='region')

    class Meta:
        model = Player
        fields = ['region']