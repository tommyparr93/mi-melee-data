from django.db import migrations, models
import django.db.models.deletion

NATIONAL_REGION_CODE = 100


def add_national_region(apps, schema_editor):
    apps.get_model('main', 'Region').objects.get_or_create(
        id=NATIONAL_REGION_CODE, defaults={'name': 'National'})


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0048_prseason_graphic_video'),
    ]

    operations = [
        migrations.CreateModel(
            name='RankingListEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_tag', models.CharField(max_length=255)),
                ('rank', models.CharField(max_length=20)),
                ('previous_rank', models.CharField(blank=True, default='', max_length=20)),
                ('score', models.FloatField(blank=True, null=True)),
                ('raw_row', models.TextField(blank=True, default='')),
                ('player', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ranking_entries', to='main.player')),
                ('pr_season', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ranking_entries', to='main.prseason')),
            ],
            options={
                'db_table': 'ranking_list_entry',
                'unique_together': {('pr_season', 'source_tag')},
            },
        ),
        migrations.AddConstraint(
            model_name='prseason',
            constraint=models.CheckConstraint(
                condition=models.Q(('is_active', True), ('region_code', NATIONAL_REGION_CODE), _negated=True),
                name='pr_season_national_never_active',
                violation_error_message='A National season cannot be the active season.',
            ),
        ),
        migrations.RunPython(add_national_region, migrations.RunPython.noop),
    ]
