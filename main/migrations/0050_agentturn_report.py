from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0049_agentbudgetday_agentturn'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentturn',
            name='reported_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='agentturn',
            name='report_note',
            field=models.TextField(blank=True),
        ),
    ]
