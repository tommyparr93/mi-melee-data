from django.contrib import admin, messages


from .models import Player, Set, Tournament, Region, PRSeason, PRSeasonResult

# 1. Register simple models as before
admin.site.register(Region)
admin.site.register(PRSeason)
admin.site.register(PRSeasonResult)
admin.site.register(Tournament)
admin.site.register(Set)


# 2. Optimized PlayerAdmin
class PlayerAdmin(admin.ModelAdmin):
    search_fields = ('name',)
    list_display = ('name', 'region_code', 'pr_notable', 'pr_eligible')
    list_filter = ('region_code', 'pr_notable', 'pr_eligible')
    list_per_page = 50

    # PERFORMANCE FIX: Replaces giant dropdown with a searchable box
    autocomplete_fields = ('main_account',)

    # SPEED FIX: Edit status without opening each player page
    list_editable = ('pr_notable', 'pr_eligible', 'region_code')
    fields = (
        'name',
        'region_code',
        'character_main',
        'character_alt',
        'pr_notable',
        'pr_eligible'
    )

    # This removes the initial list but keeps the search bar active
    def changelist_view(self, request, extra_context=None):
        search_term = request.GET.get('q')

        # If there's no search term, show an instructional message
        if not search_term:
            messages.info(request, "Search for a player by name above to view or edit their profile.")

        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        # Only restrict the queryset on the main list (changelist)
        if request.resolver_match and request.resolver_match.url_name.endswith('_changelist'):
            search_term = request.GET.get('q')
            if not search_term:
                return queryset.none()

        return queryset


# 3. Register Player with the new Admin class
admin.site.register(Player, PlayerAdmin)