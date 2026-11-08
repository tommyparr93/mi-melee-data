from django import template

from main.models import MICHIGAN_REGION_CODE, NATIONAL_REGION_CODE, PRSeasonResult
from main.views import _clean_player_tag

register = template.Library()


def build_badge_map():
    """{player_id: [Michigan badge, national badge]}, using each player's latest
    placement in each. A badge is `current` when that placement is on the newest
    published list. Summer national lists are shorter and don't set a badge."""
    results = (PRSeasonResult.objects
               .filter(pr_season__region_code_id__in=[MICHIGAN_REGION_CODE, NATIONAL_REGION_CODE])
               .exclude(pr_season__region_code_id=NATIONAL_REGION_CODE, pr_season__name__icontains='summer')
               .select_related('pr_season')
               .order_by('pr_season__start_date', 'pr_season_id'))

    latest, newest_season = {}, {}
    for result in results:
        region = result.pr_season.region_code_id
        rank = (result.rank or '').strip()
        if region == NATIONAL_REGION_CODE and not rank.isdigit():
            continue
        latest[(result.player_id, region)] = (rank, result.pr_season)
        newest_season[region] = result.pr_season_id

    badges = {}
    for region in (MICHIGAN_REGION_CODE, NATIONAL_REGION_CODE):
        for (player_id, placed_in), (rank, season) in latest.items():
            if placed_in != region:
                continue
            label = f'#{rank}' if rank.isdigit() else rank.upper()
            is_michigan = region == MICHIGAN_REGION_CODE
            badges.setdefault(player_id, []).append({
                'text': f'MI {label}' if is_michigan else f'{label} {season.name}',
                'title': f'Michigan PR: {season.name}' if is_michigan else 'National ranking',
                'is_michigan': is_michigan,
                'current': season.pk == newest_season[region],
            })
    return badges


@register.inclusion_tag('main/partials/pr_badges.html', takes_context=True)
def pr_badges(context, player):
    """Small Michigan and national rank badges for a Player. The lookup runs once
    per request, so it's safe inside loops."""
    request = context.get('request')
    badge_map = getattr(request, '_pr_badge_map', None)
    if badge_map is None:
        badge_map = build_badge_map()
        if request is not None:
            request._pr_badge_map = badge_map
    return {'badges': badge_map.get(getattr(player, 'pk', None), [])}


@register.filter
def clean_tag(name):
    """A player's name without a hand-typed national rank; the badge shows it now."""
    return _clean_player_tag(name)
