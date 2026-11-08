from django import template

from main.models import MICHIGAN_REGION_CODE, NATIONAL_REGION_CODE
from main.views import _clean_player_tag, _completed_pr_results, _pr_rank_label

register = template.Library()


def build_badge_map():
    """{player_id: badge}: one badge per player, from their latest placement on a
    completed list. The national rank wins over the Michigan one. A badge is
    `current` when that placement is on the newest completed list."""
    latest, newest_season = {}, {}
    for result in _completed_pr_results():
        region = result.pr_season.region_code_id
        if region == NATIONAL_REGION_CODE and not (result.rank or '').strip().isdigit():
            continue
        latest[(result.player_id, region)] = result
        newest_season[region] = result.pr_season_id

    badges = {}
    for region in (MICHIGAN_REGION_CODE, NATIONAL_REGION_CODE):   # national last, so it wins
        is_michigan = region == MICHIGAN_REGION_CODE
        for (player_id, placed_in), result in latest.items():
            if placed_in != region:
                continue
            label = _pr_rank_label(result.rank)
            season = result.pr_season
            badges[player_id] = {
                'text': f'MI {label}' if is_michigan else f'{label} {season.name}',
                'title': f'Michigan PR: {season.name}' if is_michigan else 'National ranking',
                'is_michigan': is_michigan,
                'current': season.pk == newest_season[region],
            }
    return badges


@register.inclusion_tag('main/partials/pr_badges.html', takes_context=True)
def pr_badges(context, player):
    """One small PR badge for a Player or player id. The lookup runs once per
    request, so it's safe inside loops."""
    request = context.get('request')
    badge_map = getattr(request, '_pr_badge_map', None)
    if badge_map is None:
        badge_map = build_badge_map()
        if request is not None:
            request._pr_badge_map = badge_map
    return {'badge': badge_map.get(getattr(player, 'pk', player))}


@register.filter
def clean_tag(name):
    """A player's name without a hand-typed national rank; the badge shows it now."""
    return _clean_player_tag(name)
