from django.db import migrations

# `pr_eligible` is a highly selective filter (currently 16 of 12,805 players)
# used on the PR H2H table (the heaviest page — builds an O(n^2) grid) and the
# eligible-players list. Without an index the planner seq-scans the whole
# player table to find eligible players on every load of those pages.
# Measured: this seq scan is the dominant cost in the pr_table query plan.
# IF NOT EXISTS keeps it idempotent/safe on the hand-built schema.


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0045_set_performance_indexes'),
    ]

    operations = [
        migrations.RunSQL(
            sql='CREATE INDEX IF NOT EXISTS idx_player_pr_eligible ON player (pr_eligible);',
            reverse_sql='DROP INDEX IF EXISTS idx_player_pr_eligible;',
        ),
    ]
