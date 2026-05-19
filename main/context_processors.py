from django.db.models import F

from .models import PRSeason

MICHIGAN_REGION_CODE = 7


def active_pr_instance(request):
    active_instance = PRSeason.objects.filter(is_active=True).first()
    # "Current MI PR" points at the most recent *finished* (not active)
    # Michigan season — newest by start date, NULL start dates last.
    current_mi_pr_season = (
        PRSeason.objects
        .filter(is_active=False, region_code_id=MICHIGAN_REGION_CODE)
        .order_by(F('start_date').desc(nulls_last=True), '-id')
        .first()
    )
    return {
        'current_pr': active_instance,
        'current_mi_pr_season': current_mi_pr_season,
    }
