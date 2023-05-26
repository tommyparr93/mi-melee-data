# Generated by Django 4.2 on 2023-05-22 14:10

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0023_rename_tour_tournamentresults_tournament_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournamentresults',
            name='id',
            field=models.BigAutoField(auto_created=True, default=1, primary_key=True, serialize=False, verbose_name='ID'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='tournamentresults',
            name='tournament_id',
            field=models.ForeignKey(db_column='tournament_id', on_delete=django.db.models.deletion.DO_NOTHING, to='main.tournament'),
        ),
    ]