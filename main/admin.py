from .models import Player, Set, Tournament, Region, PRSeason, PRSeasonResult
from django.contrib import admin


# Register your models here.


admin.site.register(Tournament)
admin.site.register(Region)
admin.site.register(PRSeason)
admin.site.register(PRSeasonResult)


class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'region_code')
    list_filter = ('region_code',)
    list_per_page = 50
    search_fields = ('name',)

class SetAdmin(admin.ModelAdmin):
    list_display = ['id', 'player1', 'player2', 'player1_score', 'player2_score', 'tournament', 'pr_eligible']  # Add 'pr_eligible' to list_display
    list_filter = ['pr_eligible']


admin.site.register(Player, PlayerAdmin)
admin.site.register(Set, SetAdmin)