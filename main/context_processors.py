from .models import PRSeason


def active_pr_instance(request):
    active_instance = PRSeason.objects.filter(is_active=True).first()
    return {
        'current_pr': active_instance
    }
