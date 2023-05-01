from .models import Player, Set, Tournament, Region
from django.contrib import admin


# Register your models here.

admin.site.register(Set)
admin.site.register(Tournament)
admin.site.register(Region)


class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'region_code')
    list_filter = ('region_code',)
    list_per_page = 50
    search_fields = ('name',)


admin.site.register(Player, PlayerAdmin)