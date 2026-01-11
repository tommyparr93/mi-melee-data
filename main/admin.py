from .models import Player, Set, Tournament, Region, PRSeason, PRSeasonResult
from django.contrib import admin


# Register your models here.


admin.site.register(Tournament)
admin.site.register(Region)
admin.site.register(PRSeason)
admin.site.register(PRSeasonResult)
admin.site.register(Set)


class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'region_code')
    list_filter = ('region_code',)
    list_per_page = 50
    search_fields = ('name',)



admin.site.register(Player, PlayerAdmin)
