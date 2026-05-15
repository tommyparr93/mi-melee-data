from django.db import migrations

# The `set` table (~105k rows) was hand-built outside Django, so the
# ForeignKey columns never got their indexes. Every player-scoped query
# (journey, player detail, analytics) does `player1 = X OR player2 = X`
# and was sequential-scanning the whole table. These B-tree indexes turn
# that into index lookups. IF NOT EXISTS keeps it idempotent/safe.


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0044_tournament_postal_code_tournament_venue_address_and_more'),
    ]

    operations = [
        migrations.RunSQL(
            sql='CREATE INDEX IF NOT EXISTS idx_set_player1 ON "set" (player1);',
            reverse_sql='DROP INDEX IF EXISTS idx_set_player1;',
        ),
        migrations.RunSQL(
            sql='CREATE INDEX IF NOT EXISTS idx_set_player2 ON "set" (player2);',
            reverse_sql='DROP INDEX IF EXISTS idx_set_player2;',
        ),
        migrations.RunSQL(
            sql='CREATE INDEX IF NOT EXISTS idx_set_tournament ON "set" (tournament_id);',
            reverse_sql='DROP INDEX IF EXISTS idx_set_tournament;',
        ),
    ]
