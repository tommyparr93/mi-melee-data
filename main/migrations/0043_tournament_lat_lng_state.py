from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0042_remove_player_character_alt_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='state',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='tournament',
            name='lat',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tournament',
            name='lng',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
