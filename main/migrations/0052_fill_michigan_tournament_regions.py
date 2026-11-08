from django.db import migrations

MICHIGAN_REGION_CODE = 7


def fill_michigan_regions(apps, schema_editor):
    """Tournaments imported before the importer set regions have a Michigan state
    but no region. Fill-only: a region that's already set is never changed."""
    apps.get_model('main', 'Tournament').objects.filter(
        region_code__isnull=True, state__in=['MI', 'Michigan'],
    ).update(region_code_id=MICHIGAN_REGION_CODE)


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0051_merge_startgg_slug_ranking_list'),
    ]

    operations = [
        migrations.RunPython(fill_michigan_regions, migrations.RunPython.noop),
    ]
