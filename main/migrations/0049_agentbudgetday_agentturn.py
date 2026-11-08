from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0048_prseason_graphic_video'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentBudgetDay',
            fields=[
                ('day', models.DateField(primary_key=True, serialize=False)),
                ('spent_usd', models.DecimalField(decimal_places=8, default=0, max_digits=12)),
                ('reserved_usd', models.DecimalField(decimal_places=8, default=0, max_digits=12)),
                ('credit_exhausted', models.BooleanField(default=False)),
            ],
            options={'db_table': 'agent_budget_day'},
        ),
        migrations.CreateModel(
            name='AgentTurn',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('source', models.CharField(default='web', max_length=10)),
                ('conversation_id', models.CharField(blank=True, db_index=True, max_length=32)),
                ('ip_hash', models.CharField(blank=True, db_index=True, max_length=32)),
                ('session_hash', models.CharField(blank=True, db_index=True, max_length=32)),
                ('backend', models.CharField(blank=True, max_length=10)),
                ('model', models.CharField(blank=True, max_length=60)),
                ('question', models.TextField()),
                ('answer', models.TextField(blank=True)),
                ('tools', models.JSONField(blank=True, default=list)),
                ('steps', models.IntegerField(default=0)),
                ('input_tokens', models.IntegerField(default=0)),
                ('output_tokens', models.IntegerField(default=0)),
                ('cache_read_tokens', models.IntegerField(default=0)),
                ('cache_write_tokens', models.IntegerField(default=0)),
                ('cost_usd', models.DecimalField(decimal_places=8, default=0, max_digits=12)),
                ('outcome', models.CharField(default='started', max_length=12)),
                ('seconds', models.FloatField(default=0)),
            ],
            options={'db_table': 'agent_turn'},
        ),
    ]
