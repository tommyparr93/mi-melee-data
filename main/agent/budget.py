"""The daily spending limit, enforced in the database so every server process shares it.

Before each model call, `reserve` holds that call's worst-case cost inside a row
lock, and `settle` swaps the hold for the real cost afterwards. Holding the money
first is what stops several simultaneous visitors from all passing the check and
overshooting together.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from main.models import AgentBudgetDay

from .base import BudgetExceeded, CreditExhausted


@dataclass(frozen=True)
class Reservation:
    day: date
    amount: Decimal


def _locked_day(day):
    AgentBudgetDay.objects.get_or_create(day=day)
    return AgentBudgetDay.objects.select_for_update().get(day=day)


class DailyBudget:
    def __init__(self, limit=None):
        self.limit = Decimal(str(limit if limit is not None else settings.ASK_TOM_DAILY_BUDGET_USD))

    def check_open(self):
        """Raise if no call could be made today. Costs no API call."""
        row = AgentBudgetDay.objects.filter(day=timezone.localdate()).first()
        if row is None:
            if self.limit <= 0:
                raise BudgetExceeded('daily budget is zero')
            return
        if row.credit_exhausted:
            raise CreditExhausted('credit flagged as exhausted today')
        if row.spent_usd + row.reserved_usd >= self.limit:
            raise BudgetExceeded('daily budget reached')

    def reserve(self, amount):
        day = timezone.localdate()
        with transaction.atomic():
            row = _locked_day(day)
            if row.credit_exhausted:
                raise CreditExhausted('credit flagged as exhausted today')
            if row.spent_usd + row.reserved_usd + amount > self.limit:
                raise BudgetExceeded('daily budget reached')
            row.reserved_usd += amount
            row.save(update_fields=['reserved_usd'])
        return Reservation(day, amount)

    def settle(self, reservation, actual):
        with transaction.atomic():
            row = _locked_day(reservation.day)
            row.reserved_usd = max(Decimal(0), row.reserved_usd - reservation.amount)
            row.spent_usd += Decimal(actual)
            row.save(update_fields=['reserved_usd', 'spent_usd'])

    def mark_credit_exhausted(self):
        """Stop calling the API for the rest of the day, so a dead balance isn't hit repeatedly."""
        day = timezone.localdate()
        with transaction.atomic():
            row = _locked_day(day)
            row.credit_exhausted = True
            row.save(update_fields=['credit_exhausted'])
