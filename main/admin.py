from django.contrib import admin
from .models import Player, Set, Tournament, Region


# Register your models here.
admin.site.register(Player)
admin.site.register(Set)
admin.site.register(Tournament)
admin.site.register(Region)
