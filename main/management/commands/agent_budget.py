from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.utils import timezone

from main.models import AgentBudgetDay, AgentTurn


class Command(BaseCommand):
    help = "Show Ask Tom's recent spending, or clear today's out-of-credit flag after topping up."

    def add_arguments(self, parser):
        parser.add_argument('--clear-credit-flag', action='store_true')

    def handle(self, *args, **options):
        if options['clear_credit_flag']:
            updated = AgentBudgetDay.objects.filter(day=timezone.localdate()).update(credit_exhausted=False)
            self.stdout.write('Cleared.' if updated else 'Nothing to clear today.')
            return
        for row in AgentBudgetDay.objects.order_by('-day')[:7]:
            flag = '  OUT OF CREDIT' if row.credit_exhausted else ''
            self.stdout.write(f'{row.day}  spent ${row.spent_usd:.4f}  on hold ${row.reserved_usd:.4f}{flag}')
        evals = AgentTurn.objects.filter(source='eval').aggregate(cost=Sum('cost_usd'), turns=Count('id'))
        self.stdout.write(f"Eval runs (not counted above): ${evals['cost'] or 0:.4f} over {evals['turns']} questions")
