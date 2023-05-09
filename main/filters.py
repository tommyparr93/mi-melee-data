from django_filters import CharFilter, FilterSet
from .models import Player

class PlayerFilter(FilterSet):
    name = CharFilter(field_name='name', lookup_expr='icontains')

    class Meta:
        model = Player
        fields = ['name']